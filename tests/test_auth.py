from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sion_api.main import create_app
from sion_api.security import is_loopback_host, require_local_bearer


def auth_client(token: str = "local-test-token"):
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    app.state.settings = app.state.settings.__class__(
        **{
            **app.state.settings.__dict__,
            "local_api_token": token,
        }
    )
    return TestClient(app)


def test_liveness_is_public_and_api_requires_bearer():
    with auth_client() as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 401
        assert client.get("/api/v1/entities").status_code == 401
        response = client.get(
            "/api/v1/entities", headers={"Authorization": "Bearer wrong"}
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        authorized = client.get(
            "/api/v1/entities", headers={"Authorization": "Bearer local-test-token"}
        )
        assert authorized.status_code == 200


def test_openapi_declares_bearer_scheme():
    with auth_client() as client:
        schema = client.get(
            "/openapi.json", headers={"Authorization": "Bearer local-test-token"}
        ).json()
        assert schema["components"]["securitySchemes"]["BearerAuth"] == {
            "type": "http", "scheme": "bearer", "bearerFormat": "opaque"
        }
        assert schema["paths"]["/api/v1/entities"]["get"]["security"] == [
            {"BearerAuth": []}
        ]


def test_non_loopback_without_token_fails_startup(monkeypatch):
    monkeypatch.setenv("SION_API_HOST", "0.0.0.0")
    monkeypatch.delenv("SION_LOCAL_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SION_LOCAL_API_TOKEN"):
        create_app(database_url="sqlite://", auto_create_schema=True)


def test_loopback_host_detection():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("127.1.2.3")
    assert is_loopback_host("::1")
    assert not is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")


def test_token_protects_documentation_endpoints():
    with auth_client() as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer local-test-token"}).status_code in {200, 307}


def test_unprotected_loopback_documentation_in_development():
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True)) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_actual_non_loopback_transport_requires_token_even_if_configured_loopback():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    local_request = SimpleNamespace(
        app=app,
        scope={"server": ("127.0.0.1", 3012), "client": ("127.0.0.1", 50000)},
    )
    assert require_local_bearer(local_request, None) is None

    exposed_request = SimpleNamespace(
        app=app,
        scope={"server": ("0.0.0.0", 3012), "client": ("192.168.1.50", 50000)},
    )
    with pytest.raises(HTTPException, match="local API token is not configured"):
        require_local_bearer(exposed_request, None)
