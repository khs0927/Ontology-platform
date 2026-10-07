"""Transactional outbox: events commit atomically with canonical writes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sion_api import models, outbox
from sion_api.main import create_app
from sqlalchemy import func, select


def _client() -> TestClient:
    return TestClient(create_app(database_url="sqlite://", auto_create_schema=True))


def _entity(c: TestClient, key: str) -> str:
    response = c.post(
        "/api/v1/entities",
        json={"stable_key": key, "entity_type_id": "Concept", "name": key, "properties": {"floors": 7}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _count(app) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(models.OutboxEvent))


def test_writes_emit_outbox_events_and_ack():
    with _client() as c:
        a = _entity(c, "concept:a")
        b = _entity(c, "concept:b")
        rel = c.post(
            "/api/v1/relations",
            json={"stable_key": "a-b", "source_entity_id": a, "target_entity_id": b, "relation_type_id": "RELATED_TO"},
        )
        assert rel.status_code == 201, rel.text
        invalidated = c.post(
            f"/api/v1/relations/{rel.json()['id']}/invalidate",
            json={"valid_to": datetime.now(timezone.utc).isoformat(), "reason": "superseded"},
        )
        assert invalidated.status_code == 200, invalidated.text

        events = c.get("/api/v1/outbox").json()
        kinds = [e["event_type"] for e in events]
        assert kinds == ["entity.created", "entity.created", "relation.created", "relation.invalidated"]
        assert events[0]["aggregate_id"] == a
        assert events[2]["payload"]["source_entity_id"] == a

        ack = c.post(
            "/api/v1/outbox/ack",
            json={"published": [e["id"] for e in events[:3]], "failed": [{"id": events[3]["id"], "error": "boom"}], "consumer": "test"},
        )
        assert ack.json() == {"published": 3, "failed": 1}
        # failed event is backed off, published ones are gone
        assert c.get("/api/v1/outbox").json() == []


def test_rejected_write_leaves_no_event():
    with _client() as c:
        _entity(c, "concept:dup")
        before = _count(c.app)
        dup = c.post("/api/v1/entities", json={"stable_key": "concept:dup", "entity_type_id": "Concept", "name": "x"})
        assert dup.status_code == 409
        assert _count(c.app) == before


def test_ingestion_paths_also_emit_events(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text("# Stair rule\nTwo direct stairs required.\n", encoding="utf-8")
    app = create_app(database_url="sqlite://", auto_create_schema=True, ingest_roots=[tmp_path])
    with TestClient(app) as c:
        response = c.post("/api/v1/ingest/documents", json={"paths": [str(doc)]})
        assert response.status_code == 200, response.text
        types = {e["event_type"] for e in c.get("/api/v1/outbox?limit=1000").json()}
    assert {"entity.created", "relation.created", "evidence.created"} <= types


def test_drain_and_backoff():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app) as c:
        _entity(c, "concept:one")
        _entity(c, "concept:two")
    factory = app.state.session_factory
    seen: list[str] = []

    def handler(event):
        if event.payload["stable_key"] == "concept:two":
            raise RuntimeError("projection down")
        seen.append(event.payload["stable_key"])

    with factory() as session:
        assert outbox.drain(session, handler, consumer="graphrag") == {"published": 1, "failed": 1}
        assert seen == ["concept:one"]
        row = session.scalars(select(models.OutboxEvent).where(models.OutboxEvent.published_at.is_(None))).one()
        assert row.attempts == 1 and "projection down" in row.last_error
        assert outbox.pending(session) == []  # backed off
        later = datetime.now(timezone.utc) + timedelta(minutes=5)
        assert [e.id for e in outbox.pending(session, now=later)] == [row.id]
        outbox.fail(session, row.id, "again")
        assert row.attempts == 2
        assert outbox.acknowledge(session, [row.id]) == 1
        assert outbox.acknowledge(session, [row.id]) == 0  # idempotent
        assert outbox.fail(session, uuid.uuid4(), "missing") is None
