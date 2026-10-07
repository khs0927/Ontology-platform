"""One PostgreSQL database: Sion core in public + ArchOntos in schema regulation.

Runs only when SION_TEST_POSTGRES_URL points at a disposable PostgreSQL with pgvector
(CI: verify.yml postgres job).
"""

from __future__ import annotations

import os

import pytest

DSN = os.getenv("SION_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="SION_TEST_POSTGRES_URL not set")


def _psycopg_url(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def test_unified_migrations_are_idempotent_and_disjoint():
    import psycopg
    from sion_api import migrate

    first = migrate.apply_core(DSN)
    assert migrate.apply_core(DSN) == []
    status = migrate.status(DSN)
    assert status["core"]["pending"] == [] and status["core"]["edited"] == []
    assert set(first) <= set(migrate.CORE_SEQUENCE)

    with psycopg.connect(DSN, autocommit=True) as conn:
        public = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert {"entities", "relations", "evidence", "artifacts", "embeddings", "outbox_events", "sion_schema_migrations"} <= public


def test_regulation_schema_side_by_side():
    pytest.importorskip("asyncpg")
    pytest.importorskip("pydantic_settings")
    import psycopg
    from sion_api import migrate

    migrate.apply_core(DSN)
    migrate.apply_regulation(DSN, schema="regulation")
    assert migrate.apply_regulation(DSN, schema="regulation") == []
    with psycopg.connect(DSN, autocommit=True) as conn:
        regulation = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='regulation'")}
        public = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        vector_schema = conn.execute(
            "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE extname='vector'"
        ).fetchone()[0]
    assert {"outbox_message", "rule", "rule_version", "assertion", "evidence_span", "schema_migrations"} <= regulation
    assert not ({"outbox_message", "rule", "assertion"} & public)  # ArchOntos never lands in public
    assert vector_schema == "public"
    assert migrate.status(DSN)["regulation"]["pending"] == []


def test_api_on_postgres_writes_outbox_atomically():
    from fastapi.testclient import TestClient
    from sion_api import migrate
    from sion_api.main import create_app

    migrate.apply_core(DSN)
    app = create_app(database_url=_psycopg_url(DSN), auto_create_schema=False)
    key = f"concept:pg-outbox-{os.getpid()}"
    with TestClient(app) as c:
        created = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Concept", "name": key})
        assert created.status_code == 201, created.text
        events = [e for e in c.get("/api/v1/outbox?limit=1000").json() if e["payload"].get("stable_key") == key]
        assert [e["event_type"] for e in events] == ["entity.created"]
        assert c.post("/api/v1/outbox/ack", json={"published": [events[0]["id"]]}).json()["published"] == 1
        dup = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Concept", "name": key})
        assert dup.status_code == 409
        again = [e for e in c.get("/api/v1/outbox?limit=1000").json() if e["payload"].get("stable_key") == key]
        assert again == []
