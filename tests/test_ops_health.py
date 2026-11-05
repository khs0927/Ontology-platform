from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
from sion_api import ops
from sion_api.auth import AuthPolicy
from sion_api.main import create_app

TOKEN = "test-only-ops-secret-token-value"
SECRET_DSN_PART = "s3cr3t-password"


def _app(**kwargs):
    return create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        auth_policy=AuthPolicy(mode="bearer", token_scopes=((TOKEN, frozenset({"*"})),)),
        **kwargs,
    )


def test_liveness_needs_no_auth_and_no_database():
    with TestClient(_app()) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "service", "version"}


def test_readiness_ok_with_reachable_database():
    with TestClient(_app()) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok"}
    assert body["database"] == "sqlite"


def test_readiness_failure_returns_503_without_leaking_connection_details():
    app = _app()

    class _BrokenEngine:
        dialect = app.state.engine.dialect

        def connect(self):
            raise RuntimeError(f"could not connect to postgresql://sion:{SECRET_DSN_PART}@db.internal:5432/sion")

    # Rebuild the probes against a broken engine on a fresh app instance.
    from fastapi import FastAPI

    probe_app = FastAPI()
    ops.register(probe_app, _BrokenEngine(), "test")
    with TestClient(probe_app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "version": "test", "checks": {"database": "unavailable"}}
    assert SECRET_DSN_PART not in response.text
    assert "db.internal" not in response.text


def test_readiness_does_not_write(tmp_path):
    db = tmp_path / "ready.db"
    app = create_app(database_url=f"sqlite:///{db}", auto_create_schema=True,
                     auth_policy=AuthPolicy(mode="local-only"))
    before = db.read_bytes()
    with TestClient(app) as client:
        for _ in range(3):
            assert client.get("/health/ready").status_code == 200
    assert db.read_bytes() == before


def test_access_log_redacts_authorization_and_query_strings(caplog):
    with caplog.at_level(logging.INFO, logger=ops.ACCESS_LOGGER_NAME):
        with TestClient(_app()) as client:
            response = client.get(
                "/api/v1/entities?email=person%40example.com&token=abc",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Cookie": "session=cookie-secret-value",
                    "X-Request-ID": "req-12345678",
                },
            )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-12345678"
    records = [r.getMessage() for r in caplog.records if r.name == ops.ACCESS_LOGGER_NAME]
    assert records, "expected an access-log line"
    joined = "\n".join(records)
    assert TOKEN not in joined
    assert "Bearer" not in joined
    assert "cookie-secret-value" not in joined
    assert "person" not in joined and "example.com" not in joined
    entry = json.loads(records[-1])
    assert entry == {
        "event": "http_request",
        "request_id": "req-12345678",
        "method": "GET",
        "path": "/api/v1/entities",
        "status": 200,
        "duration_ms": entry["duration_ms"],
    }


def test_access_log_replaces_unsafe_request_id_and_logs_failed_auth(caplog):
    with caplog.at_level(logging.INFO, logger=ops.ACCESS_LOGGER_NAME):
        with TestClient(_app()) as client:
            response = client.get(
                "/api/v1/entities",
                headers={"Authorization": "Bearer wrong-token-value-123456", "X-Request-ID": "bad id\nInjected"},
            )
    assert response.status_code == 401
    entry = json.loads([r.getMessage() for r in caplog.records if r.name == ops.ACCESS_LOGGER_NAME][-1])
    assert entry["status"] == 401
    assert entry["request_id"] != "bad id\nInjected"
    assert "wrong-token-value" not in json.dumps(entry)


def test_access_log_can_be_disabled(caplog, monkeypatch):
    monkeypatch.setenv("SION_API_ACCESS_LOG", "0")
    with caplog.at_level(logging.INFO, logger=ops.ACCESS_LOGGER_NAME):
        with TestClient(_app()) as client:
            assert client.get("/health/live").status_code == 200
    assert not [r for r in caplog.records if r.name == ops.ACCESS_LOGGER_NAME]


def test_redact_headers_helper():
    redacted = ops.redact_headers({
        "Authorization": f"Bearer {TOKEN}",
        "Proxy-Authorization": "Basic dXNlcjpwYXNz",
        "X-Forwarded-Note": f"bearer {TOKEN}",
        "Accept": "application/json",
    })
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["Proxy-Authorization"] == "[REDACTED]"
    assert TOKEN not in redacted["X-Forwarded-Note"]
    assert redacted["Accept"] == "application/json"
