from __future__ import annotations

from sion_ingestion.dlp import Classification, DLPScanner, scan_payload


SYNTHETIC_HMAC_KEY = b"synthetic-dlp-test-key-not-for-production"


def test_public_payload_is_allowed_unchanged():
    payload = {"title": "synthetic fixture", "count": 2, "enabled": True, "missing": None}

    decision = scan_payload(payload, hmac_key=SYNTHETIC_HMAC_KEY)

    assert decision.allowed is True
    assert decision.action == "allowed"
    assert decision.sanitized_payload == payload
    assert decision.findings == ()


def test_recursive_scan_classifies_and_sanitizes_every_requested_kind():
    secret = "sion_test_secret_ABC123_fixture"
    bearer = "Bearer synthetic-token-123456"
    private_key = "-----BEGIN PRIVATE KEY-----"
    dsn = "postgresql://synthetic_user:synthetic_password@example.invalid/db"
    email = "person@example.invalid"
    phone = "010-1234-5678"
    payload = {
        "nested": [{"secret": secret}],
        "headers": {"authorization": bearer},
        "private": private_key,
        "dsn": dsn,
        "pii": {"email": email, "phone": phone},
        "source_uri": "file:///synthetic/source.json",
    }

    decision = scan_payload(payload, hmac_key=SYNTHETIC_HMAC_KEY, cwd="C:/synthetic/cwd")
    kinds = {finding.kind for finding in decision.findings}

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert {
        "synthetic_secret",
        "authorization",
        "private_key_header",
        "dsn_credential",
        "email",
        "phone",
        "source_uri",
    } <= kinds
    serialized = repr(decision)
    for raw in (secret, bearer, private_key, dsn, email, phone):
        assert raw not in serialized
    assert decision.sanitized_payload["headers"]["authorization"] == "[REDACTED:SECRET]"
    assert decision.sanitized_payload["pii"]["email"].startswith("[PII:")
    assert decision.sanitized_payload["pii"]["phone"].startswith("[PII:")


def test_bearer_in_text_and_authorization_are_secret_findings():
    decision = scan_payload(
        {"one": "Authorization: Basic synthetic-credential", "two": "Bearer opaque-synthetic-value"},
        hmac_key=SYNTHETIC_HMAC_KEY,
    )

    assert {(finding.kind, finding.classification) for finding in decision.findings} == {
        ("authorization", Classification.SECRET),
        ("bearer_token", Classification.SECRET),
    }
    assert decision.sanitized_payload["one"] == "[REDACTED:SECRET]"
    assert decision.sanitized_payload["two"] == "[REDACTED:SECRET]"


def test_pii_tokenization_is_deterministic_and_uses_injected_key():
    payload = {"email": "person@example.invalid"}
    first = scan_payload(payload, hmac_key=SYNTHETIC_HMAC_KEY)
    second = scan_payload(payload, hmac_key=SYNTHETIC_HMAC_KEY)
    other_key = scan_payload(payload, hmac_key=b"another-synthetic-test-key")

    assert first.sanitized_payload == second.sanitized_payload
    assert first.sanitized_payload["email"] != other_key.sanitized_payload["email"]
    assert first.action == "tokenized"
    assert first.metadata["tokenized"] is True
    assert first.allowed is False


def test_pii_without_hmac_key_fails_closed_without_exposing_value():
    value = "person@example.invalid"
    decision = scan_payload({"email": value})

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert decision.metadata["reason"] == "pii_tokenization_key_required"
    assert decision.sanitized_payload["email"] == "[REDACTED:PII]"
    assert value not in repr(decision)


def test_cwd_and_user_home_paths_are_findings():
    scanner = DLPScanner(hmac_key=SYNTHETIC_HMAC_KEY, cwd="C:/synthetic/project")
    decision = scanner.scan({"path": "C:/synthetic/project/input.json"})

    assert decision.findings[0].kind == "cwd"
    assert decision.findings[0].classification is Classification.INTERNAL
    assert "C:/synthetic/project" not in repr(decision)


def test_findings_and_metadata_are_json_serializable_without_raw_values():
    secret = "fake_secret_fixture_value"
    decision = scan_payload({"token": secret}, hmac_key=SYNTHETIC_HMAC_KEY)
    result = decision.to_dict()

    assert result["findings"] == [
        {
            "path": "$.token",
            "classification": "SECRET",
            "kind": "synthetic_secret",
        }
    ]
    assert secret not in str(result)
    assert "sanitized_payload" not in result
    assert decision.sanitized_payload == {"token": "[REDACTED:SECRET]"}


def test_secret_in_mapping_key_is_sanitized():
    secret = "fake_secret_fixture_key"
    decision = scan_payload({secret: "synthetic value"}, hmac_key=SYNTHETIC_HMAC_KEY)

    assert decision.allowed is False
    assert secret not in repr(decision)
    assert list(decision.sanitized_payload) == ["[REDACTED:SECRET]"]


def test_scanner_error_from_object_conversion_fails_closed():
    class SyntheticExplodingObject:
        def __str__(self) -> str:
            raise RuntimeError("synthetic conversion failure")

    decision = scan_payload({"bad": SyntheticExplodingObject()}, hmac_key=SYNTHETIC_HMAC_KEY)

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert decision.sanitized_payload is None
    assert decision.metadata == {"reason": "scanner_error", "fail_closed": True}


def test_node_limit_fails_closed_without_exception_or_payload():
    decision = scan_payload(
        {"many": list(range(20))}, hmac_key=SYNTHETIC_HMAC_KEY, max_nodes=5
    )

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert decision.sanitized_payload is None
    assert decision.metadata == {"reason": "scan_limit_exceeded", "fail_closed": True}


def test_finding_limit_fails_closed():
    decision = scan_payload(
        [f"person{index}@example.invalid" for index in range(4)],
        hmac_key=SYNTHETIC_HMAC_KEY,
        max_findings=2,
    )

    assert decision.allowed is False
    assert decision.sanitized_payload is None
    assert decision.metadata["reason"] == "scan_limit_exceeded"


def test_unsupported_value_fails_closed():
    class SyntheticUnsupported:
        def __repr__(self) -> str:
            return "synthetic unsupported fixture"

    decision = scan_payload({"object": SyntheticUnsupported()}, hmac_key=SYNTHETIC_HMAC_KEY)

    assert decision.allowed is False
    assert decision.action == "quarantine"
    assert decision.findings[0].classification is Classification.UNKNOWN
    assert decision.sanitized_payload["object"] == "[REDACTED:UNKNOWN]"
