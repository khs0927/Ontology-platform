from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from sion_api.health import check_readiness
from sion_api.main import create_app


def test_liveness_does_not_depend_on_database():
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True)) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert "database" not in response.json()


def test_authenticated_sqlite_readiness_uses_logical_schema():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    app.state.settings = app.state.settings.__class__(
        **{**app.state.settings.__dict__, "local_api_token": "test-token"}
    )
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 401
        response = client.get(
            "/health/ready", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ready"
        assert body["components"]["schema"]["status"] == "ok"
        assert body["components"]["revision"]["status"] == "ok"


def test_missing_core_table_is_not_ready_with_stable_reason():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE entities (id INTEGER PRIMARY KEY)"))
    result = check_readiness(engine)
    assert result["status"] == "not_ready"
    assert result["components"]["schema"]["reason"] == "core_schema_missing"
    assert "sqlite:///" not in str(result)
    assert "SELECT" not in str(result)


def test_postgresql_revision_and_vector_checks_are_componentized(monkeypatch):
    # The behavioral contract is tested against the real SQLite backend here;
    # PostgreSQL-specific branches are guarded by dialect rather than by
    # pretending SQLite is PostgreSQL or by exposing driver exceptions.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in (
            "entity_types", "relation_types", "entities", "ontology_versions",
            "artifacts", "documents", "chunks", "relations", "evidence",
        ):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
    result = check_readiness(engine, vector_enabled=True)
    assert result["status"] == "not_ready"
    assert result["components"]["revision"]["status"] == "ok"
    assert result["components"]["vector"]["reason"] == "vector_postgres_required"
