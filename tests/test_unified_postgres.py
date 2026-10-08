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
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        created = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Concept", "name": key})
        assert created.status_code == 201, created.text
        events = [e for e in c.get("/api/v1/outbox?limit=1000").json() if e["payload"].get("stable_key") == key]
        assert [e["event_type"] for e in events] == ["entity.created"]
        assert c.post("/api/v1/outbox/ack", json={"published": [events[0]["id"]]}).json()["published"] == 1
        dup = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Concept", "name": key})
        assert dup.status_code == 409
        again = [e for e in c.get("/api/v1/outbox?limit=1000").json() if e["payload"].get("stable_key") == key]
        assert again == []


def test_concurrent_review_decisions_are_atomic_on_postgres():
    """PR #44 review: N reviewers read the same pending candidate, then decide at once; exactly one wins."""
    import threading
    import uuid

    from sion_api import migrate, models, review
    from sion_api.db import build_engine, build_session_factory
    from sqlalchemy import select

    migrate.apply_core(DSN)
    engine = build_engine(_psycopg_url(DSN))
    factory = build_session_factory(engine)
    tag = uuid.uuid4().hex[:12]
    with factory() as s:
        a = models.Entity(stable_key=f"concept:race-a-{tag}", entity_type_id="Concept", name="race a")
        b = models.Entity(stable_key=f"concept:race-b-{tag}", entity_type_id="Concept", name="race b")
        s.add_all([a, b])
        s.flush()
        rel = models.Relation(stable_key=f"race:{tag}", source_entity_id=a.id, target_entity_id=b.id,
                              relation_type_id="RELATED_TO", verification_state="unverified", source_kind="inferred",
                              confidence=0.5, properties={"candidate": True, "extractor": "test"})
        s.add(rel)
        s.flush()
        s.add(models.Evidence(relation_id=rel.id, source_uri=f"test://race/{tag}", verification_state="unverified",
                              properties={}))
        s.commit()
        rid = rel.id

    workers = 8
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(i: int) -> None:
        with factory() as session:
            stale = session.get(models.Relation, rid)  # noqa: F841 - pinned stale read (pending)
            barrier.wait()
            try:
                if i % 3 == 2:
                    res = review.decide_bulk(session, [str(rid)], approve=i % 2 == 0, note="race", reviewer=f"r{i}")
                    outcome = res["results"][0]["result"]
                else:
                    review.decide(session, rid, approve=i % 2 == 0, reviewer=f"r{i}", note="race")
                    outcome = "applied"
            except review.AlreadyReviewed:
                outcome = "conflict"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(outcomes) == workers
    assert outcomes.count("applied") == 1, outcomes
    assert set(outcomes) <= {"applied", "conflict", "unchanged"}
    with factory() as s:
        row = s.get(models.Relation, rid)
        decision = row.properties["review"]["decision"]
        assert row.verification_state == ("human_verified" if decision == "approved" else "rejected")
        evidence_states = {e.verification_state for e in s.scalars(select(models.Evidence).where(models.Evidence.relation_id == rid))}
        assert evidence_states == {row.verification_state}
        updates = s.scalars(select(models.OutboxEvent).where(models.OutboxEvent.aggregate_id == rid)
                            .where(models.OutboxEvent.event_type == "relation.updated")).all()
        assert len(updates) == 1
    engine.dispose()
