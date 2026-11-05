"""Hermetic safety tests for the read-only Sion operational preflight."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_ontology_readonly.py"
spec = importlib.util.spec_from_file_location("audit_ontology_readonly", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def fake_api(requests, payloads):
    def open_request(request, timeout):
        requests.append((request.get_method(), request.full_url, request.get_header("Authorization"), timeout))
        name = request.full_url.split("https://example.test")[-1]
        item = payloads[name]
        if isinstance(item, int):
            raise HTTPError(request.full_url, item, "test", {}, None)
        if isinstance(item, Exception):
            raise item
        return Response(json.dumps(item).encode())
    return open_request


def responses():
    return {
        "/health": {"status": "ok"},
        "/health/ready": {"checks": {"database": "ok"}},
        "/api/v1/graphrag/status": {"configured": True, "answers_enabled": True, "canonical": False, "embedding_model": "private-model"},
        "/api/v1/storage/status": {"status": "ok", "private_path": "/private/path"},
        "/api/v1/aec/status": {"configured": True, "secret": "untrusted"},
    }


def test_preflight_is_get_only_and_redacted():
    requests = []
    result = module.audit("https://example.test", token="synthetic-secret", open_request=fake_api(requests, responses()))
    assert result["configuration_preflight_passed"] is True
    assert result["end_to_end_verified"] is False
    assert len(requests) == len(module.CHECK_PATHS)
    assert all(r[0] == "GET" for r in requests)
    assert all(r[2] is None for r in requests[:2])
    assert all(r[2] == "Bearer synthetic-secret" for r in requests[2:])
    assert not any(secret in json.dumps(result) for secret in ("synthetic-secret", "private-model", "/private/path", "untrusted", "example.test"))


def test_without_token_skips_private_checks():
    requests = []
    result = module.audit("https://example.test", open_request=fake_api(requests, responses()))
    assert [r[1] for r in requests] == ["https://example.test/health", "https://example.test/health/ready"]
    assert result["checks"]["graphrag"]["result"] == "skipped_no_token"
    assert not result["configuration_preflight_passed"]


def test_legacy_api_does_not_claim_ready():
    requests = []
    payloads = responses()
    payloads["/health/ready"] = 404
    payloads["/api/v1/graphrag/status"] = {"configured": False, "canonical": False}
    result = module.audit("https://example.test", token="synthetic", open_request=fake_api(requests, payloads))
    assert result["checks"]["readiness"]["result"] == "not_implemented"
    assert not result["checks"]["graphrag"]["configured"]
    assert not result["configuration_preflight_passed"]


def test_http_errors_are_sanitized():
    payloads = responses()
    payloads["/api/v1/graphrag/status"] = 403
    payloads["/api/v1/storage/status"] = OSError("SECRET DSN")
    result = module.audit("https://example.test", token="synthetic", open_request=fake_api([], payloads))
    assert result["checks"]["graphrag"]["result"] == "unauthorized"
    assert result["checks"]["storage"]["result"] == "unreachable"
    assert "SECRET DSN" not in json.dumps(result)


def test_oversized_response_is_rejected():
    payloads = responses()
    payloads["/api/v1/storage/status"] = {"large": "x" * 70000}
    result = module.audit("https://example.test", token="synthetic", open_request=fake_api([], payloads))
    assert result["checks"]["storage"]["result"] == "oversized_response"


@pytest.mark.parametrize("url", [
    "http://example.test", "http://example.test/", "https://user:pass@example.test",
    "https://example.test/path", "https://example.test/?token=secret", "https://example.test/#a",
    "file:///tmp/sion", "https://example.test\nX-Evil: x",
])
def test_unsafe_base_urls_rejected(url):
    with pytest.raises(ValueError):
        module.validate_base_url(url)


def test_http_localhost_allowed():
    assert module.validate_base_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert module.validate_base_url("http://[::1]:8000") == "http://[::1]:8000"


def test_redirects_denied():
    h = module._NoRedirect()
    request = module.Request("https://example.test/api/v1/graphrag/status", headers={"Authorization": "Bearer synthetic"})
    assert h.redirect_request(request, None, 302, "redirect", {}, "https://evil.test/") is None
