"""Fail-closed contract for high-confidence credential shapes.

The reviewed source tree is the object under test, so the module is loaded
directly from ``packages/ingestion/sion_ingestion/dlp.py`` rather than through
whatever ``sion_ingestion`` copy happens to be installed in the environment.

Two properties are asserted for every shape:

1. a credential is reported as a ``SECRET`` finding and the decision is closed;
2. neither the raw value nor any of it survives in the sanitized payload,
   findings, or decision metadata.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DLP_PATH = ROOT / "packages" / "ingestion" / "sion_ingestion" / "dlp.py"


def _load_dlp():
    if not DLP_PATH.is_file():
        pytest.skip(f"reviewed dlp module not present at {DLP_PATH}")
    spec = importlib.util.spec_from_file_location("sion_dlp_under_review", DLP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dlp = _load_dlp()
SECRET = dlp.Classification.SECRET

# (test id, secret payload, expected finding kind)
SECRET_SHAPES: tuple[tuple[str, str, str], ...] = (
    (
        "synthetic_skill_token",
        "sk-THIS-SECRET-MUST-NOT-PERSIST",
        "sk_prefix_token",
    ),
    (
        "openai_style_project_key",
        "sk-proj-Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr",
        "sk_prefix_token",
    ),
    (
        "keyword_qualified_api_key",
        'api_key = "Zx8Qw3Er7Ty2Ui1Op4As6Df9Gh"',
        "api_key_assignment",
    ),
    (
        "x_api_key_header",
        "X-Api-Key: 4f7b1c9d2e6a8b0c3d5f7e9a1b3c5d7e",
        "api_key_assignment",
    ),
    (
        "bearer_client_secret",
        "client_secret=9Kd2Lp7Zq4Wv8Xc1Nb6Hy3Rt0S",
        "api_key_assignment",
    ),
    (
        "basic_auth_header",
        "Basic QWxhZGRpbjpvcGVuc2VzYW1lMTIzNDU2",
        "basic_auth_header",
    ),
    (
        "json_web_token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVP",
        "jwt",
    ),
    (
        "aws_access_key_id",
        "AKIAIOSFODNN7EXAMPLE",
        "aws_access_key_id",
    ),
    (
        "aws_secret_access_key",
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "aws_secret_access_key",
    ),
)

# Strings that name a credential but carry no credential. Broadening the
# scanner must not turn ordinary prose into a blocked payload.
BENIGN_SHAPES: tuple[str, ...] = (
    "the api key rotation is scheduled for next sprint",
    "rotate the client secret before the release cut",
    "authorization header missing",
    "sk-learn is a machine learning library",
    "sk-short-id",
    "AKIA",
    "eyJhbGciOiJIUzI1NiJ9",
    "AWS_SECRET_ACCESS_KEY is unset in this environment",
)


def _scan(payload: object):
    return dlp.scan_payload(payload, cwd=str(ROOT / "no-such-root"))


def _serialized(decision) -> str:
    return json.dumps(
        {
            "sanitized": decision.sanitized_payload,
            "findings": [finding.to_dict() for finding in decision.findings],
            "metadata": decision.metadata,
            "action": decision.action,
        },
        ensure_ascii=False,
        default=str,
    )


@pytest.mark.parametrize(
    ("payload", "expected_kind"), [item[1:] for item in SECRET_SHAPES], ids=[i[0] for i in SECRET_SHAPES]
)
def test_credential_shape_is_reported_as_secret_and_blocks(payload: str, expected_kind: str):
    decision = _scan({"session": {"payload": payload}})

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert decision.metadata["highest_classification"] == SECRET.value

    secret_findings = [f for f in decision.findings if f.classification is SECRET]
    assert secret_findings, f"no SECRET finding for {expected_kind}"
    assert expected_kind in {f.kind for f in secret_findings}
    assert all(f.path.startswith("$") for f in secret_findings)


@pytest.mark.parametrize(
    ("payload", "expected_kind"), [item[1:] for item in SECRET_SHAPES], ids=[i[0] for i in SECRET_SHAPES]
)
def test_credential_raw_value_never_persists(payload: str, expected_kind: str):
    decision = _scan({"session": {"payload": payload}})

    serialized = _serialized(decision)
    token = payload.split("=")[-1].split(":")[-1].strip().strip("\"'")
    assert token not in serialized
    assert payload not in serialized

    sanitized = decision.sanitized_payload["session"]["payload"]
    assert dlp._REDACTIONS[SECRET] in sanitized
    assert token not in sanitized


@pytest.mark.parametrize("payload", BENIGN_SHAPES)
def test_benign_mentions_are_not_flagged_as_secrets(payload: str):
    decision = _scan({"note": payload})

    assert not [
        f for f in decision.findings if f.classification is SECRET
    ], f"benign text flagged as SECRET: {payload}"


def test_synthetic_skill_token_alone_blocks_the_cycle_payload():
    """The exact token used by the blocked-cycle fault contract."""

    decision = _scan({"payload": "sk-THIS-SECRET-MUST-NOT-PERSIST"})

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert any(f.kind == "sk_prefix_token" for f in decision.findings)
    assert "sk-THIS-SECRET-MUST-NOT-PERSIST" not in _serialized(decision)


def test_secret_anywhere_in_a_nested_payload_closes_the_decision():
    decision = _scan(
        {
            "nodes": [
                {"properties": {"cwd": "somewhere-else"}},
                {"properties": {"note": "harmless"}},
            ],
            "edges": [{"payload": "AKIAIOSFODNN7EXAMPLE"}],
        }
    )

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert any(
        f.classification is SECRET and f.kind == "aws_access_key_id"
        for f in decision.findings
    )
    assert "AKIAIOSFODNN7EXAMPLE" not in _serialized(decision)


def test_scanner_fails_closed_when_hmac_bound_secret_scan_errors(monkeypatch):
    """A scanner fault must produce a closed decision, not an allowed one."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected scanner fault")

    monkeypatch.setattr(dlp.DLPScanner, "_visit_string", _boom)
    decision = dlp.scan_payload({"payload": "AKIAIOSFODNN7EXAMPLE"})

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert decision.sanitized_payload is None
    assert decision.metadata == {"reason": "scanner_error", "fail_closed": True}
