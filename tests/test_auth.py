from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from sion_api.auth import ApiAuthConfig, BearerPrincipal, authorize_request
from sion_api.main import create_app


class FakeAecAdapter:
    enabled = True

    def query_global_memory(self, question, *, top_k=10, project_id=None):
        return {
            "route": "GLOBAL_MEMORY",
            "query": question,
            "hits": [
                {
                    "project_id": project_id or "P1",
                    "object_id": "aec://object/door-1",
                    "score": 0.9,
                }
            ],
        }


def _request(path: str, *, method: str = "GET", host: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": (host, 54321),
            "server": ("127.0.0.1", 8000),
        }
    )


def _token_config() -> ApiAuthConfig:
    return ApiAuthConfig(
        mode="token",
        principals=(
            BearerPrincipal("aec-reader", frozenset({"read:aec"}), name="power-cad"),
            BearerPrincipal("admin-token", frozenset({"*"}), name="admin"),
        ),
    )


def test_local_mode_denies_remote_clients_and_allows_loopback():
    config = ApiAuthConfig(mode="local")
    local = authorize_request(_request("/api/v1/aec/query"), config)
    remote = authorize_request(
        _request("/api/v1/aec/query", host="203.0.113.10"),
        config,
    )
    assert local.allowed is True
    assert remote.allowed is False
    assert remote.status_code == 403
    assert remote.required_scope == "read:aec"


def test_token_mode_requires_bearer_even_from_local_test_client():
    app = create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        aec_adapter=FakeAecAdapter(),
        auth_config=_token_config(),
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

        missing = client.get("/api/v1/aec/query", params={"question": "door"})
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"

        invalid = client.get(
            "/api/v1/aec/query",
            params={"question": "door"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert invalid.status_code == 401


def test_read_aec_scope_can_query_federation_but_cannot_write_knowledge():
    app = create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        aec_adapter=FakeAecAdapter(),
        auth_config=_token_config(),
    )
    headers = {"Authorization": "Bearer aec-reader"}
    with TestClient(app) as client:
        query = client.get(
            "/api/v1/aec/query",
            params={"question": "door", "project_id": "P-AEC"},
            headers=headers,
        )
        assert query.status_code == 200
        assert query.json()["canonical"] is False
        assert query.json()["read_only"] is True

        denied = client.post(
            "/api/v1/entities",
            headers=headers,
            json={
                "stable_key": "concept:blocked",
                "entity_type_id": "Concept",
                "name": "Blocked",
                "properties": {},
            },
        )
        assert denied.status_code == 403
        assert denied.json()["required_scope"] == "write:knowledge"


def test_admin_scope_can_write_and_read_knowledge():
    app = create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        auth_config=_token_config(),
    )
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/entities",
            headers=headers,
            json={
                "stable_key": "concept:allowed",
                "entity_type_id": "Concept",
                "name": "Allowed",
                "properties": {},
            },
        )
        assert created.status_code == 201, created.text
        listed = client.get("/api/v1/entities", headers=headers)
        assert listed.status_code == 200
        assert any(row["stable_key"] == "concept:allowed" for row in listed.json())
