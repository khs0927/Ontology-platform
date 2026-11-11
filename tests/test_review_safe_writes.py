"""Issue #71 steps E/F: safe /review writes.

* optimistic concurrency (``expected_version`` compare-and-swap, 409 with the current version)
* ``dry_run`` returns the exact would-be result and writes nothing
* every applied transition leaves a replayable decision-log entry
* low-trust inferred edges need an explicit human confirmation flag to be approved
* backward compatibility: no ``expected_version`` still works unless strict mode is on
* the review page is phone-usable and shows evidence locator / source checksum
"""

from __future__ import annotations

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
CAND = "/api/v1/relations/candidates"


def make_client(tmp_path: Path, **kwargs) -> TestClient:
    policy = AuthPolicy(mode="bearer", token_scopes=((WRITE, frozenset({"read:knowledge", "write:knowledge"})),))
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'review.db'}",
        auto_create_schema=True,
        auth_policy=policy,
        ingest_roots=[ROOT / "data"],
        **kwargs,
    )
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))


@pytest.fixture()
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def import_candidates(c: TestClient) -> list[str]:
    r = c.post("/api/v1/import/graph-export", json={"path": str(SOURCE), "expected_node_count": 31, "expected_edge_count": 43}, headers=AUTH)
    assert r.status_code == 200, r.text
    return [x["id"] for x in c.get(f"{CAND}?limit=1000", headers=AUTH).json()["candidates"]]


def detail(c: TestClient, rid: str) -> dict:
    return c.get(f"{CAND}/{rid}", headers=AUTH).json()


def outbox_count(c: TestClient, rid: str) -> int:
    with c.app.state.session_factory() as s:
        return len(list(s.scalars(select(models.OutboxEvent).where(models.OutboxEvent.aggregate_id == uuid.UUID(rid)))))


def stored(c: TestClient, rid: str) -> models.Relation:
    with c.app.state.session_factory() as s:
        return s.get(models.Relation, uuid.UUID(rid))


# --- optimistic concurrency -------------------------------------------------------------------


def test_expected_version_is_a_compare_and_swap(client):
    rid = import_candidates(client)[0]
    assert detail(client, rid)["version"] == 0

    stale = client.post(f"{CAND}/{rid}/approve", json={"reviewer": "alice", "expected_version": 3}, headers=AUTH)
    assert stale.status_code == 409
    body = stale.json()["detail"]
    assert body["error"] == "version_conflict" and body["current_version"] == 0 and body["expected_version"] == 3
    assert body["status"] == "pending"
    assert detail(client, rid)["status"] == "pending"  # nothing written

    ok = client.post(f"{CAND}/{rid}/approve", json={"reviewer": "alice", "expected_version": 0}, headers=AUTH)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved" and ok.json()["version"] == 1

    # a second reviewer still holding version 0 learns the current version, not just "already approved"
    late = client.post(f"{CAND}/{rid}/reject", json={"reviewer": "bob", "expected_version": 0}, headers=AUTH)
    assert late.status_code == 409 and late.json()["detail"]["current_version"] == 1
    assert late.json()["detail"]["status"] == "approved"

    # reopen honours the version too; an A->B->A cycle cannot let the stale version through
    assert client.post(f"{CAND}/{rid}/reopen", json={"note": "oops", "expected_version": 0}, headers=AUTH).status_code == 409
    assert client.post(f"{CAND}/{rid}/reopen", json={"note": "oops", "expected_version": 1}, headers=AUTH).status_code == 200
    aba = client.post(f"{CAND}/{rid}/reject", json={"expected_version": 0}, headers=AUTH)
    assert aba.status_code == 409 and aba.json()["detail"]["current_version"] == 2
    assert client.post(f"{CAND}/{rid}/reject", json={"expected_version": 2}, headers=AUTH).json()["version"] == 3


def test_bulk_expected_versions_report_per_item_conflict_with_current_version(client):
    ids = import_candidates(client)
    assert client.post(f"{CAND}/{ids[0]}/approve", json={}, headers=AUTH).status_code == 200
    assert client.post(f"{CAND}/{ids[0]}/reopen", json={"note": "recheck"}, headers=AUTH).status_code == 200
    # ids[0] is pending again but at version 2: a reviewer who loaded it at version 0 must reload
    body = client.post(
        BULK,
        json={"ids": ids[:3], "decision": "reject", "note": "batch", "expected_versions": {ids[0]: 0, ids[1]: 0}},
        headers=AUTH,
    ).json()
    by_id = {r["id"]: r for r in body["results"]}
    assert by_id[ids[0]]["result"] == "conflict" and by_id[ids[0]]["version"] == 2 and by_id[ids[0]]["ok"] is False
    assert "version" in by_id[ids[0]]["reason"]
    assert by_id[ids[1]]["result"] == "applied" and by_id[ids[1]]["version"] == 1
    assert by_id[ids[2]]["result"] == "applied"  # no expected version listed -> legacy behaviour
    # #99 response contract is unchanged
    assert set(body["counts"]) == set(review.BULK_RESULTS)
    assert {"decision", "batch_id", "requested", "succeeded", "failed", "counts", "results"} <= set(body)
    assert detail(client, ids[0])["status"] == "pending"


# --- dry run ----------------------------------------------------------------------------------


def test_single_dry_run_returns_would_be_result_and_writes_nothing(client):
    rid = import_candidates(client)[0]
    events = outbox_count(client, rid)
    preview = client.post(f"{CAND}/{rid}/approve", json={"reviewer": "alice", "note": "n", "dry_run": True, "expected_version": 0}, headers=AUTH)
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["dry_run"] is True and p["status"] == "approved" and p["version"] == 1
    assert p["review"]["reviewer"] == "alice"
    after = detail(client, rid)
    assert after["status"] == "pending" and after["version"] == 0 and after["review"] is None
    assert outbox_count(client, rid) == events
    assert "review_log" not in stored(client, rid).properties
    assert all(e["verification_state"] == "unverified" for e in after["evidence"])

    real = client.post(f"{CAND}/{rid}/approve", json={"reviewer": "alice", "note": "n", "expected_version": 0}, headers=AUTH).json()
    assert {k: v for k, v in real.items() if k != "review"} == {k: v for k, v in p.items() if k not in ("review", "dry_run")}

    # a dry run that would fail fails the same way
    assert client.post(f"{CAND}/{rid}/reject", json={"dry_run": True}, headers=AUTH).status_code == 409
    undo = client.post(f"{CAND}/{rid}/reopen", json={"note": "x", "dry_run": True}, headers=AUTH)
    assert undo.status_code == 200 and undo.json()["status"] == "pending" and undo.json()["dry_run"] is True
    assert detail(client, rid)["status"] == "approved"


def test_bulk_dry_run_matches_the_real_call_and_writes_nothing(client):
    ids = import_candidates(client)
    assert client.post(f"{CAND}/{ids[1]}/reject", json={}, headers=AUTH).status_code == 200
    payload = {"ids": [ids[0], ids[1], ids[2], "nope"], "decision": "approve", "note": "batch", "reviewer": "khs"}
    dry = client.post(BULK, json={**payload, "dry_run": True}, headers=AUTH).json()
    assert dry["dry_run"] is True and dry["batch_id"] is None
    assert all(r["batch_id"] is None for r in dry["results"])
    counts = client.get(CAND, headers=AUTH).json()["counts"]
    assert counts == {"pending": 42, "approved": 0, "rejected": 1}

    real = client.post(BULK, json=payload, headers=AUTH).json()
    assert real["dry_run"] is False and real["batch_id"]
    strip = lambda rs: [{k: v for k, v in r.items() if k not in ("batch_id", "detail", "reason")} for r in rs]  # noqa: E731
    assert strip(dry["results"]) == strip(real["results"])
    assert dry["counts"] == real["counts"] and dry["succeeded"] == real["succeeded"]


# --- audit log --------------------------------------------------------------------------------


def test_every_transition_has_a_replayable_audit_record(client):
    ids = import_candidates(client)
    rid = ids[0]
    assert client.post(f"{CAND}/{rid}/approve", json={"reviewer": "alice", "note": "looks right"}, headers=AUTH).status_code == 200
    assert client.post(f"{CAND}/{rid}/reopen", json={"reviewer": "alice", "note": "wrong target"}, headers=AUTH).status_code == 200
    bulk = client.post(BULK, json={"ids": [rid], "decision": "reject", "note": "dup edge", "reviewer": "bob"}, headers=AUTH).json()

    audit = client.get(f"{CAND}/{rid}/audit", headers=AUTH)
    assert audit.status_code == 200
    a = audit.json()
    assert a["consistent"] is True and a["replay"]["errors"] == []
    assert a["current"] == {"state": "rejected", "status": "rejected", "version": 3}
    log = a["log"]
    assert [e["action"] for e in log] == ["approved", "reopened", "rejected"]
    assert [(e["prior_state"], e["new_state"]) for e in log] == [
        ("unverified", "human_verified"), ("human_verified", "unverified"), ("unverified", "rejected")]
    assert [(e["from_version"], e["to_version"]) for e in log] == [(0, 1), (1, 2), (2, 3)]
    assert [e["reviewer"] for e in log] == ["alice", "alice", "bob"]
    assert [e["note"] for e in log] == ["looks right", "wrong target", "dup edge"]
    assert log[2]["batch_id"] == bulk["batch_id"] and log[0]["batch_id"] is None
    assert all(e["at"] for e in log)

    # the log alone reproduces the stored state; a tampered/reordered log does not replay
    assert review.replay_log(log)["state"] == "rejected"
    assert review.replay_log([log[0], log[2]])["errors"]

    # an untouched candidate replays trivially; an unknown id is 404
    fresh = client.get(f"{CAND}/{ids[5]}/audit", headers=AUTH).json()
    assert fresh["log"] == [] and fresh["consistent"] is True
    assert client.get(f"{CAND}/{uuid.uuid4()}/audit", headers=AUTH).status_code == 404


# --- backward compatibility and strict mode ---------------------------------------------------


def test_missing_expected_version_still_works_by_default(client):
    ids = import_candidates(client)
    assert client.post(f"{CAND}/{ids[0]}/approve", headers=AUTH).status_code == 200
    assert client.post(f"{CAND}/{ids[1]}/reject", json={"note": "no"}, headers=AUTH).status_code == 200
    assert client.post(BULK, json={"ids": ids[2:4], "decision": "approve", "note": "ok"}, headers=AUTH).json()["counts"]["applied"] == 2
    # legacy 409 bodies stay plain strings
    legacy = client.post(f"{CAND}/{ids[0]}/reject", headers=AUTH)
    assert legacy.status_code == 409 and legacy.json()["detail"] == "candidate already approved"


def test_strict_mode_requires_expected_version(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_REVIEW_REQUIRE_VERSION", "1")
    with make_client(tmp_path) as c:
        ids = import_candidates(c)
        r = c.post(f"{CAND}/{ids[0]}/approve", json={}, headers=AUTH)
        assert r.status_code == 428 and r.json()["detail"]["error"] == "version_required"
        b = c.post(BULK, json={"ids": ids[:2], "decision": "approve", "note": "x", "expected_versions": {ids[0]: 0}}, headers=AUTH)
        assert b.status_code == 428 and b.json()["detail"]["ids"] == [ids[1]]
        assert c.get(CAND, headers=AUTH).json()["counts"]["approved"] == 0
        assert c.post(f"{CAND}/{ids[0]}/approve", json={"expected_version": 0}, headers=AUTH).status_code == 200
        ok = c.post(BULK, json={"ids": ids[1:3], "decision": "reject", "note": "x", "expected_versions": {ids[1]: 0, ids[2]: 0}}, headers=AUTH)
        assert ok.status_code == 200 and ok.json()["counts"]["applied"] == 2
        assert c.post(f"{CAND}/{ids[0]}/reopen", json={"note": "x"}, headers=AUTH).status_code == 428


def test_strict_mode_can_be_set_explicitly(tmp_path, monkeypatch):
    monkeypatch.delenv("SION_REVIEW_REQUIRE_VERSION", raising=False)
    with make_client(tmp_path, review_require_version=True) as c:
        rid = import_candidates(c)[0]
        assert c.post(f"{CAND}/{rid}/approve", json={}, headers=AUTH).status_code == 428


# --- low-trust inferred edges -----------------------------------------------------------------


def add_low_trust_candidate(c: TestClient) -> str:
    a = c.post("/api/v1/entities", json={"stable_key": "lt:a", "entity_type_id": "Project", "name": "A"}, headers=AUTH).json()
    b = c.post("/api/v1/entities", json={"stable_key": "lt:b", "entity_type_id": "Tool", "name": "B"}, headers=AUTH).json()
    with c.app.state.session_factory() as s:
        row = models.Relation(
            stable_key="lt:a:RELATED_TO:lt:b",
            source_entity_id=uuid.UUID(a["id"]),
            target_entity_id=uuid.UUID(b["id"]),
            relation_type_id="RELATED_TO",
            confidence=0.25,
            verification_state="unverified",
            source_kind="inferred",
            properties={"candidate": True, "extractor": "sion-relation-extractor/v1", "rules": ["co-occurrence"], "support": 2},
        )
        s.add(row)
        s.commit()
        return str(row.id)


def test_low_trust_edge_needs_explicit_confirmation_to_approve(client):
    ids = import_candidates(client)
    rid = add_low_trust_candidate(client)
    assert detail(client, rid)["low_trust"] is True and detail(client, ids[0])["low_trust"] is False

    r = client.post(f"{CAND}/{rid}/approve", json={"reviewer": "alice"}, headers=AUTH)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "low_trust_confirmation_required"
    assert client.post(f"{CAND}/{rid}/approve", json={"dry_run": True}, headers=AUTH).status_code == 422
    b = client.post(BULK, json={"ids": [ids[0], rid], "decision": "approve", "note": "x"}, headers=AUTH)
    assert b.status_code == 422 and b.json()["detail"]["ids"] == [rid]
    assert detail(client, ids[0])["status"] == "pending"  # the whole request was refused
    assert detail(client, rid)["status"] == "pending"

    # rejecting needs no confirmation; approving with the flag records it in the audit trail
    assert client.post(f"{CAND}/{rid}/reject", json={"dry_run": True}, headers=AUTH).status_code == 200
    ok = client.post(f"{CAND}/{rid}/approve", json={"reviewer": "alice", "confirm_low_trust": True}, headers=AUTH)
    assert ok.status_code == 200 and ok.json()["review"]["confirmed_low_trust"] is True
    assert client.get(f"{CAND}/{rid}/audit", headers=AUTH).json()["log"][0]["confirmed_low_trust"] is True


# --- evidence locator / checksum and the phone-usable page ------------------------------------


def test_candidates_expose_source_locator_and_checksum(client):
    rid = import_candidates(client)[0]
    d = detail(client, rid)
    assert d["source_sha256"] and len(d["source_sha256"]) == 64
    assert d["source_locator"]
    assert d["evidence"] and all("source_sha256" in e for e in d["evidence"])


def test_document_sourced_candidates_are_listed_and_decidable(client):
    # The SketchUp guideline links are stored with source_kind="document". Listing only
    # inferred/imported hid them from /review even though docs/SKETCHUP_KNOWLEDGE.md says
    # they are review candidates, so the owner's queue was silently incomplete.
    import_candidates(client)
    a = client.post("/api/v1/entities", json={"stable_key": "doc:a", "entity_type_id": "Document", "name": "A"}, headers=AUTH).json()
    b = client.post("/api/v1/entities", json={"stable_key": "doc:b", "entity_type_id": "Document", "name": "B"}, headers=AUTH).json()
    with client.app.state.session_factory() as s:
        row = models.Relation(
            stable_key="doc:a:DERIVED_FROM:doc:b",
            source_entity_id=uuid.UUID(a["id"]),
            target_entity_id=uuid.UUID(b["id"]),
            relation_type_id="DERIVED_FROM",
            confidence=0.9,
            verification_state="unverified",
            source_kind="document",
            properties={"candidate": True, "extractor": "sion-sketchup-assets/v1"},
        )
        s.add(row)
        s.commit()
        doc_id = str(row.id)

    listed = [x["id"] for x in client.get(f"{CAND}?limit=1000", headers=AUTH).json()["candidates"]]
    assert doc_id in listed, "document-sourced candidates must reach /review"

    ok = client.post(f"{CAND}/{doc_id}/approve", json={"reviewer": "alice", "expected_version": 0}, headers=AUTH)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"


def test_review_page_is_phone_usable_and_sends_safe_write_fields(client):
    page = client.get("/review").text
    assert 'name="viewport"' in page and "@media (max-width" in page
    for needle in ("expected_version", "expected_versions", "dry_run", "confirm_low_trust", "source_sha256", "version_conflict"):
        assert needle in page, needle
