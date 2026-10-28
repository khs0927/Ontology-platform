"""Issue #80 step 3: the /review approval weight boost is bounded and idempotent."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_api import models
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_graphrag import build_custom_kg
from sion_graphrag.projection import (
    APPROVAL_WEIGHT_BOOST,
    BASE_RELATION_WEIGHT,
    MAX_RELATION_WEIGHT,
    relation_weight,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "sources" / "sion-map-production.json"
WRITE = "write-token-12345678901"
AUTH = {"Authorization": f"Bearer {WRITE}"}


def test_cap_constants_are_consistent():
    assert MAX_RELATION_WEIGHT == BASE_RELATION_WEIGHT + 1.0
    assert 0 < APPROVAL_WEIGHT_BOOST < MAX_RELATION_WEIGHT - BASE_RELATION_WEIGHT


@pytest.mark.parametrize("conf", [None, -1.0, 0.0, 0.5, 0.9, 1.0, 5.0])
@pytest.mark.parametrize("state", ["unverified", "machine_verified", "human_verified", "rejected", None])
def test_weight_never_exceeds_cap(conf, state):
    w = relation_weight(conf, state)
    assert BASE_RELATION_WEIGHT <= w <= MAX_RELATION_WEIGHT


def test_approval_boost_values():
    assert relation_weight(0.5, "unverified") == pytest.approx(1.5)
    assert relation_weight(0.5, "human_verified") == pytest.approx(1.75)
    assert relation_weight(0.9, "human_verified") == pytest.approx(MAX_RELATION_WEIGHT)  # capped, not 2.15
    assert relation_weight(0.9, "unverified") == pytest.approx(1.9)  # existing behaviour unchanged


def _weight(c: TestClient, rid: str) -> tuple[float, float | None]:
    with c.app.state.session_factory() as session:
        row = session.get(models.Relation, uuid.UUID(rid))
        conf, key = row.confidence, row.stable_key
        [rel] = [r for r in build_custom_kg(session)["relationships"] if r["source_id"] == f"sion:relation:{key}"]
    return rel["weight"], conf


def test_repeated_approvals_do_not_raise_weight(tmp_path):
    policy = AuthPolicy(mode="bearer", token_scopes=((WRITE, frozenset({"read:knowledge", "write:knowledge"})),))
    app = create_app(database_url=f"sqlite:///{tmp_path / 'w.db'}", auto_create_schema=True, auth_policy=policy, ingest_roots=[ROOT / "data"])
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        r = c.post("/api/v1/import/graph-export", json={"path": str(SOURCE), "expected_node_count": 31, "expected_edge_count": 43}, headers=AUTH)
        assert r.status_code == 200, r.text
        rid = c.get("/api/v1/relations/candidates?limit=1", headers=AUTH).json()["candidates"][0]["id"]
        base, conf = _weight(c, rid)
        expected = relation_weight(conf, "human_verified")
        assert base == pytest.approx(relation_weight(conf, "unverified"))
        weights = []
        for i in range(5):  # approve -> reopen -> approve ... grows review_history, not weight
            assert c.post(f"/api/v1/relations/candidates/{rid}/approve", json={"reviewer": "mus"}, headers=AUTH).status_code == 200
            weights.append(_weight(c, rid)[0])
            # a second approve while decided is refused and cannot stack a boost
            assert c.post(f"/api/v1/relations/candidates/{rid}/approve", headers=AUTH).status_code == 409
            assert _weight(c, rid)[0] == pytest.approx(weights[-1])
            assert c.post(f"/api/v1/relations/candidates/{rid}/reopen", json={"note": f"cycle {i}"}, headers=AUTH).status_code == 200
            assert _weight(c, rid)[0] == pytest.approx(base)
        assert weights == pytest.approx([expected] * 5)
        assert max(weights) <= MAX_RELATION_WEIGHT
