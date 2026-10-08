from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app

TOKEN = "test-only-local-boundary-token"


@pytest.fixture
def app():
    return create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=AuthPolicy(mode="local-only"))


@pytest.mark.parametrize("host", ["attacker.example", "localhost.attacker.example", "127.0.0.1.attacker.example",
                                  "localhost:bad", "localhost/path", "user@localhost"])
def test_loopback_peer_cannot_bypass_host_check(app, host):
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/v1/entities", headers={"Host": host}).status_code == 403
        assert client.post("/api/v1/entities", json={}, headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("headers", [
    {"Origin": "https://attacker.example"}, {"Origin": "null"},
    {"Origin": "http://localhost.attacker.example"}, {"Origin": "http://localhost/"},
    {"Sec-Fetch-Site": "cross-site"},
    [("Host", "localhost"), ("Host", "attacker.example")],
    [("Origin", "http://localhost"), ("Origin", "https://attacker.example")],
])
def test_browser_requests_are_rejected_before_body_or_database(app, headers):
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/v1/entities", headers=headers).status_code == 403
        assert client.post("/api/v1/entities", json={}, headers=headers).status_code == 403


def test_same_origin_native_clients_and_explicit_development_origins(app):
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        for headers in ({}, {"Origin": "http://localhost"}, {"Origin": "http://localhost:3000"}):
            assert client.get("/api/v1/entities", headers=headers).status_code == 200


@pytest.mark.parametrize("peer", ["testclient", "localhost", "203.0.113.7"])
def test_local_identity_comes_from_peer_ip(app, peer):
    with TestClient(app, base_url="http://localhost", client=(peer, 50000)) as client:
        assert client.get("/api/v1/entities").status_code == 403


def test_local_or_bearer_requires_token_for_untrusted_browser_requests():
    app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=AuthPolicy(
        mode="local-or-bearer", token_scopes=((TOKEN, frozenset({"read:knowledge"})),)))
    with TestClient(app, base_url="http://attacker.example", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/v1/entities").status_code == 401
        assert client.get("/api/v1/entities", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
        assert client.post("/api/v1/entities", json={}, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 403


def test_non_ascii_bearer_is_rejected_without_server_error():
    app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=AuthPolicy(
        mode="bearer", token_scopes=((TOKEN, frozenset({"*"})),)))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/v1/entities", headers=[(b"Authorization", b"Bearer \xff")]).status_code == 401
