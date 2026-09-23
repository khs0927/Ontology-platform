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
