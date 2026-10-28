"""Issue #80 step 1: filter GraphRAG projection/weights by review state."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sion_api import models
from sion_api.main import create_app
from sion_graphrag.projection import build_custom_kg, resolve_verification_states
from sqlalchemy import select

STATES = {
    "aec:a|RELATED_TO|aec:hv": "human_verified",
    "aec:a|RELATED_TO|aec:mv": "machine_verified",
    "aec:a|RELATED_TO|aec:un": "unverified",
    "aec:a|RELATED_TO|aec:rj": "rejected",
}


@pytest.fixture()
def kg_for():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        ids = {}
        for key in ("aec:a", "aec:hv", "aec:mv", "aec:un", "aec:rj"):
            r = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Project", "name": key, "properties": {}})
            assert r.status_code == 201, r.text
            ids[key] = r.json()["id"]
        for stable_key in STATES:
            target = stable_key.rsplit("|", 1)[1]
            r = c.post("/api/v1/relations", json={
                "stable_key": stable_key, "source_entity_id": ids["aec:a"], "target_entity_id": ids[target],
                "relation_type_id": "RELATED_TO", "confidence": 0.5,
            })
            assert r.status_code == 201, r.text
        with app.state.session_factory() as session:
            for rel in session.scalars(select(models.Relation)):
                rel.verification_state = STATES[rel.stable_key]
            session.commit()

        def run(review_states):
            with app.state.session_factory() as session:
                kg = build_custom_kg(session, review_states=review_states)
            return {r["tgt_id"]: r for r in kg["relationships"]}, kg

        yield run


def test_no_filter_keeps_all_states(kg_for):
    rels, _ = kg_for(None)
    assert set(rels) == {"aec:hv", "aec:mv", "aec:un", "aec:rj"}


def test_filter_verified_only(kg_for):
    rels, kg = kg_for(["verified"])
    assert set(rels) == {"aec:hv", "aec:mv"}
    assert rels["aec:mv"]["weight"] == pytest.approx(1.5)
    assert rels["aec:hv"]["weight"] == pytest.approx(1.75)  # approval boost (step 3)
    assert not any("sion:relation:aec:a|RELATED_TO|aec:rj" == c["source_id"] for c in kg["chunks"])


def test_filter_unverified_only(kg_for):
    rels, _ = kg_for(["unverified"])
    assert set(rels) == {"aec:un"}
    assert "verification_state: unverified" in rels["aec:un"]["description"]


def test_filter_rejected_only(kg_for):
    rels, _ = kg_for(["rejected"])
    assert set(rels) == {"aec:rj"}


def test_filter_verified_and_unverified_excludes_rejected(kg_for):
    rels, kg = kg_for(["verified", "unverified"])
    assert "aec:rj" not in rels and len(rels) == 3
    # Entities are still projected even when their relation is filtered out.
    assert "aec:rj" in {e["entity_name"] for e in kg["entities"]}


def test_raw_state_and_empty_filter(kg_for):
    assert set(kg_for(["human_verified"])[0]) == {"aec:hv"}
    assert kg_for([])[0] == {}


def test_unknown_review_state_rejected():
    with pytest.raises(ValueError):
        resolve_verification_states(["approved"])
    assert resolve_verification_states(None) is None
