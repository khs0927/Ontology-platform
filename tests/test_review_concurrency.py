"""PR #44 review: pending -> decided must be an atomic compare-and-set.

Two reviewers that both read a candidate as ``unverified`` can no longer both report success; the
second one gets 409 / ``conflict`` and the first decision + audit record stay intact. ``reopen`` is the
supported way to undo a decision. The PostgreSQL variant lives in tests/test_unified_postgres.py.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_api import models, review
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "sources" / "sion-map-production.json"
WRITE = "write-token-12345678901"
AUTH = {"Authorization": f"Bearer {WRITE}"}
BULK = "/api/v1/relations/candidates/bulk"


def make_client(database_url: str) -> TestClient:
    policy = AuthPolicy(mode="bearer", token_scopes=((WRITE, frozenset({"read:knowledge", "write:knowledge"})),))
    app = create_app(database_url=database_url, auto_create_schema=True, auth_policy=policy, ingest_roots=[ROOT / "data"])
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))


def import_candidates(c: TestClient) -> list[str]:
    r = c.post("/api/v1/import/graph-export", json={"path": str(SOURCE), "expected_node_count": 31, "expected_edge_count": 43}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = c.get("/api/v1/relations/candidates?limit=1000", headers=AUTH).json()
    return [x["id"] for x in body["candidates"]]


@pytest.fixture()
def client(tmp_path):
    # A file database: every session has its own connection/transaction, like the real server.
    with make_client(f"sqlite:///{tmp_path / 'review.db'}") as c:
        yield c


def stale_session(c: TestClient, rid: str):
    """A second reviewer's session that has already read the candidate as pending.

    The row is pinned on the session (the identity map only holds weak references), so later
    ``session.get`` calls return this stale object exactly like a real interleaved request would.
    """
    session = c.app.state.session_factory()
    row = session.get(models.Relation, uuid.UUID(rid))
    assert row.verification_state == "unverified"
    session.info.setdefault("pinned", []).append(row)
    return session


def committed(c: TestClient, rid: str) -> models.Relation:
    with c.app.state.session_factory() as s:
        return s.get(models.Relation, uuid.UUID(rid))


def outbox_count(c: TestClient, rid: str) -> int:
    with c.app.state.session_factory() as s:
        return len(list(s.scalars(select(models.OutboxEvent).where(models.OutboxEvent.aggregate_id == uuid.UUID(rid))
                                  .where(models.OutboxEvent.event_type == "relation.updated"))))


def test_stale_per_item_decision_loses_instead_of_overwriting(client):
    rid = import_candidates(client)[0]
    other = stale_session(client, rid)
    try:
        first = client.post(f"/api/v1/relations/candidates/{rid}/approve", json={"reviewer": "alice", "note": "ok"}, headers=AUTH)
        assert first.status_code == 200
        with pytest.raises(review.AlreadyReviewed, match="approved"):
            review.decide(other, uuid.UUID(rid), approve=False, reviewer="bob", note="no")
    finally:
        other.close()
    row = committed(client, rid)
    assert row.verification_state == "human_verified"
    assert row.properties["review"]["reviewer"] == "alice" and row.properties["review"]["decision"] == "approved"
    assert outbox_count(client, rid) == 1  # the winner still emits exactly one relation.updated event


def test_stale_bulk_decision_reports_conflict_or_unchanged(client):
    ids = import_candidates(client)
    rid, same = ids[0], ids[1]
    other = stale_session(client, rid)
    other.info["pinned"].append(other.get(models.Relation, uuid.UUID(same)))
    try:
        assert client.post(f"/api/v1/relations/candidates/{rid}/reject", json={"reviewer": "alice"}, headers=AUTH).status_code == 200
        assert client.post(f"/api/v1/relations/candidates/{same}/approve", json={"reviewer": "alice"}, headers=AUTH).status_code == 200
        result = review.decide_bulk(other, [rid, same, ids[2]], approve=True, note="batch", reviewer="bob")
    finally:
        other.close()
    by_id = {r["id"]: r for r in result["results"]}
    assert by_id[rid]["result"] == "conflict" and by_id[rid]["status"] == "rejected"
    assert by_id[same]["result"] == "unchanged"
    assert by_id[ids[2]]["result"] == "applied"
    assert committed(client, rid).properties["review"]["reviewer"] == "alice"
    assert committed(client, same).properties["review"]["reviewer"] == "alice"  # audit record not rewritten
    assert committed(client, ids[2]).properties["review"]["batch_id"] == result["batch_id"]


def race(factory, rid: str, workers: int = 6) -> list[str]:
    """Each worker reads the candidate as pending, waits for the others, then decides (alternating)."""
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(i: int) -> None:
        with factory() as session:
            pinned = session.get(models.Relation, uuid.UUID(rid))  # noqa: F841 - keep the stale read alive
            barrier.wait()
            try:
                review.decide(session, uuid.UUID(rid), approve=i % 2 == 0, reviewer=f"r{i}", note="race")
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
    return outcomes


def test_concurrent_opposite_decisions_exactly_one_wins(client):
    rid = import_candidates(client)[0]
    outcomes = race(client.app.state.session_factory, rid)
    assert sorted(outcomes) == ["applied"] + ["conflict"] * 5
    row = committed(client, rid)
    winner = row.properties["review"]
    assert row.verification_state == ("human_verified" if winner["decision"] == "approved" else "rejected")
    assert outbox_count(client, rid) == 1


def test_reopen_is_the_supported_undo_and_keeps_history(client):
    rid = import_candidates(client)[0]
    assert client.post(f"/api/v1/relations/candidates/{rid}/approve", json={"reviewer": "alice", "note": "ok"}, headers=AUTH).status_code == 200
    # the opposite decision is still refused while decided
    assert client.post(f"/api/v1/relations/candidates/{rid}/reject", headers=AUTH).status_code == 409
    url = f"/api/v1/relations/candidates/{rid}/reopen"
    assert client.post(url, json={"note": "x"}).status_code == 401  # write scope required
    assert client.post(url, json={"note": "   "}, headers=AUTH).status_code == 422  # note required
    r = client.post(url, json={"note": "approved by mistake", "reviewer": "alice"}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending" and body["review"] is None
    assert body["evidence"] and all(e["verification_state"] == "unverified" for e in body["evidence"])
    history = committed(client, rid).properties["review_history"]
    assert history[0]["decision"] == "approved" and history[0]["reverted_state"] == "human_verified"
    assert history[0]["reopen_note"] == "approved by mistake"
    assert client.post(url, json={"note": "again"}, headers=AUTH).status_code == 409  # already pending
    again = client.post(f"/api/v1/relations/candidates/{rid}/reject", json={"reviewer": "alice", "note": "right call"}, headers=AUTH)
    assert again.status_code == 200 and again.json()["status"] == "rejected"
    counts = client.get("/api/v1/relations/candidates", headers=AUTH).json()["counts"]
    assert counts["rejected"] == 1 and counts["approved"] == 0


def test_stale_reopen_loses_to_a_concurrent_reopen(client):
    rid = import_candidates(client)[0]
    assert client.post(f"/api/v1/relations/candidates/{rid}/approve", headers=AUTH).status_code == 200
    other = client.app.state.session_factory()
    try:
        pinned = other.get(models.Relation, uuid.UUID(rid))
        assert pinned.verification_state == "human_verified"
        assert client.post(f"/api/v1/relations/candidates/{rid}/reopen", json={"note": "first"}, headers=AUTH).status_code == 200
        assert client.post(f"/api/v1/relations/candidates/{rid}/reject", headers=AUTH).status_code == 200
        with pytest.raises(review.AlreadyReviewed):
            review.reopen(other, uuid.UUID(rid), note="stale")
    finally:
        other.close()
    row = committed(client, rid)
    assert row.verification_state == "rejected" and len(row.properties["review_history"]) == 1


def test_review_page_refreshes_totals_and_offers_undo(client):
    page = client.get("/review").text
    decide = page[page.index("async function decide"): page.index("async function reopen")]
    bulk = page[page.index("async function bulk"): page.index("// ---- display-only")]
    # PR #44 review: the header totals are re-read after per-item and bulk decisions (and after a 409)
    assert decide.count("await refreshCounts()") == 2
    assert "await refreshCounts()" in bulk
    assert "/reopen" in page and "되돌리기" in page
