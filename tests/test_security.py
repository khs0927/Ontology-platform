from fastapi.testclient import TestClient

from ontology_api.main import create_app


def test_write_api_is_closed_when_token_mode_has_no_token():
    with TestClient(create_app("sqlite+pysqlite:///:memory:", security_mode="token")) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health/security").json() == {
            "mode": "token",
            "write_auth_configured": False,
        }
        response = client.post(
            "/entities",
            json={"stable_key": "security:closed", "entity_type_id": "Concept", "name": "Closed"},
        )
        assert response.status_code == 503


def test_write_api_requires_valid_bearer_token():
    with TestClient(
        create_app(
            "sqlite+pysqlite:///:memory:",
            security_mode="token",
            api_token="test-secret-token",
        )
    ) as client:
        payload = {"stable_key": "security:entity", "entity_type_id": "Concept", "name": "Secured"}
        assert client.post("/entities", json=payload).status_code == 401
        assert client.post(
            "/entities",
            json=payload,
            headers={"Authorization": "Bearer wrong-token"},
        ).status_code == 401
        created = client.post(
            "/entities",
            json=payload,
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert created.status_code == 201, created.text
        assert client.get(f"/entities/{created.json()['id']}").status_code == 200


def test_disabled_mode_is_explicit_and_reports_configuration_state():
    with TestClient(
        create_app("sqlite+pysqlite:///:memory:", security_mode="disabled")
    ) as client:
        assert client.get("/health/security").json() == {
            "mode": "disabled",
            "write_auth_configured": True,
        }
        created = client.post(
            "/entities",
            json={"stable_key": "security:disabled", "entity_type_id": "Concept", "name": "Local"},
        )
        assert created.status_code == 201


def test_private_mode_protects_reads_writes_and_openapi():
    with TestClient(create_app("sqlite+pysqlite:///:memory:", security_mode="private")) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/graph").status_code == 503
        assert client.post("/entities", json={}).status_code == 503

    with TestClient(create_app(
        "sqlite+pysqlite:///:memory:", security_mode="private", api_token="private-test-token"
    )) as client:
        assert client.get("/health/security").json()["write_auth_configured"] is True
        for path in ("/graph", "/evidence", "/openapi.json", "/health/db"):
            denied = client.get(path)
            assert denied.status_code == 401
            assert denied.headers["WWW-Authenticate"] == "Bearer"
            assert client.get(path, headers={"Authorization": "Bearer private-test-token"}).status_code == 200
        payload = {"stable_key": "private:entity", "entity_type_id": "Concept", "name": "Private"}
        assert client.post("/entities", json=payload).status_code == 401
        assert client.post("/entities", json=payload, headers={"Authorization": "Bearer wrong"}).status_code == 401
        created = client.post("/entities", json=payload, headers={"Authorization": "Bearer private-test-token"})
        assert created.status_code == 201, created.text

        openapi = client.get(
            "/openapi.json",
            headers={"Authorization": "Bearer private-test-token"},
        ).json()
        public_paths = {"/health", "/health/security"}
        http_methods = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
        for path, path_item in openapi["paths"].items():
            for method, operation in path_item.items():
                if method.lower() not in http_methods:
                    continue
                if path in public_paths:
                    assert "security" not in operation
                else:
                    assert operation["security"] == [{"HTTPBearer": []}]
