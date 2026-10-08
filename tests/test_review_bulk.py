"""Bulk review API: explicit ids only, note required, per-item audit trail, idempotent."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sion_api import models
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "sources" / "sion-map-production.json"
WRITE = "write-token-12345678901"
READ = "read-token-123456789012"
AUTH = {"Authorization": f"Bearer {WRITE}"}
BULK = "/api/v1/relations/candidates/bulk"


def client() -> TestClient:
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=(
            (WRITE, frozenset({"read:knowledge", "write:knowledge"})),
            (READ, frozenset({"read:knowledge"})),
        ),
    )
    app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy, ingest_roots=[ROOT / "data"])
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))


def pending_ids(c: TestClient) -> list[str]:
    r = c.post("/api/v1/import/graph-export", json={"path": str(SOURCE), "expected_node_count": 31, "expected_edge_count": 43}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = c.get("/api/v1/relations/candidates?limit=1000", headers=AUTH).json()
    assert body["total"] == 43
    return [x["id"] for x in body["candidates"]]


def test_bulk_requires_write_scope_and_note():
    with client() as c:
        ids = pending_ids(c)
        payload = {"ids": ids[:2], "decision": "approve", "note": "checked"}
        assert c.post(BULK, json=payload).status_code == 401
        assert c.post(BULK, json=payload, headers={"Authorization": f"Bearer {READ}"}).status_code == 403
        assert c.post(BULK, json={"ids": ids[:2], "decision": "approve"}, headers=AUTH).status_code == 422
        assert c.post(BULK, json={**payload, "note": "   "}, headers=AUTH).status_code == 422
        assert c.post(BULK, json={**payload, "ids": []}, headers=AUTH).status_code == 422
        assert c.post(BULK, json={**payload, "decision": "auto"}, headers=AUTH).status_code == 422
        # nothing was decided by the refused calls
        assert c.get("/api/v1/relations/candidates", headers=AUTH).json()["counts"] == {"pending": 43, "approved": 0, "rejected": 0}


def test_bulk_audit_trail_matches_per_item_and_is_idempotent():
    with client() as c:
        ids = pending_ids(c)
        single = c.post(f"/api/v1/relations/candidates/{ids[0]}/approve", json={"reviewer": "khs", "note": "one"}, headers=AUTH)
        assert single.status_code == 200
        r = c.post(BULK, json={"ids": ids[1:4], "decision": "approve", "note": "map edges checked", "reviewer": "khs"}, headers=AUTH)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"] == "approved" and body["counts"]["applied"] == 3 and body["batch_id"]
        assert [x["id"] for x in body["results"]] == ids[1:4]

        per_item = c.get(f"/api/v1/relations/candidates/{ids[0]}", headers=AUTH).json()
        for rid in ids[1:4]:
            detail = c.get(f"/api/v1/relations/candidates/{rid}", headers=AUTH).json()
            review = detail["review"]
            assert detail["verification_state"] == "human_verified" and detail["status"] == "approved"
            # identical audit keys to the per-item route, plus the shared batch id
            assert set(review) - {"batch_id"} == set(per_item["review"])
            assert review["reviewer"] == "khs" and review["note"] == "map edges checked"
            assert review["previous_state"] == "unverified" and review["batch_id"] == body["batch_id"]
            assert detail["evidence"] and all(e["verification_state"] == "human_verified" for e in detail["evidence"])
        with c.app.state.session_factory() as session:
            rows = list(session.scalars(select(models.Evidence).where(models.Evidence.relation_id.in_([uuid.UUID(i) for i in ids[1:4]]))))
        assert rows and all(e.properties["review"]["batch_id"] == body["batch_id"] for e in rows)
        assert {e.properties["review"]["decision"] for e in rows} == {"approved"} and {e.verification_state for e in rows} == {"human_verified"}

        before = c.get(f"/api/v1/relations/candidates/{ids[1]}", headers=AUTH).json()["review"]
        again = c.post(BULK, json={"ids": ids[:4], "decision": "approve", "note": "repeat"}, headers=AUTH).json()
        assert again["counts"]["unchanged"] == 4 and again["counts"]["applied"] == 0 and again["batch_id"] is None
        assert c.get(f"/api/v1/relations/candidates/{ids[1]}", headers=AUTH).json()["review"] == before
        # the opposite decision does not overwrite a human decision
        flip = c.post(BULK, json={"ids": ids[1:2], "decision": "reject", "note": "flip"}, headers=AUTH).json()
        assert flip["results"][0]["result"] == "conflict" and flip["results"][0]["status"] == "approved"
        counts = c.get("/api/v1/relations/candidates", headers=AUTH).json()["counts"]
        assert counts == {"pending": 39, "approved": 4, "rejected": 0}


def test_bulk_mixed_and_unknown_ids():
    with client() as c:
        ids = pending_ids(c)
        a = c.post("/api/v1/entities", json={"stable_key": "p:a", "entity_type_id": "Project", "name": "A"}, headers=AUTH).json()
        b = c.post("/api/v1/entities", json={"stable_key": "p:b", "entity_type_id": "Tool", "name": "B"}, headers=AUTH).json()
        plain = c.post("/api/v1/relations", json={"stable_key": "p:a:USES:p:b", "source_entity_id": a["id"], "target_entity_id": b["id"],
                                                   "relation_type_id": "USES", "verification_state": "human_verified"}, headers=AUTH).json()
        missing = str(uuid.uuid4())
        payload = {"ids": [ids[0], missing, "not-a-uuid", plain["id"], ids[1], ids[0]], "decision": "reject", "note": "co-occurrence only"}
        body = c.post(BULK, json=payload, headers=AUTH).json()
        results = {x["id"]: x["result"] for x in body["results"]}
        assert results == {ids[0]: "applied", missing: "not_found", "not-a-uuid": "invalid_id",
                           plain["id"]: "not_candidate", ids[1]: "applied"}
        assert body["requested"] == 5  # duplicates collapse to one result
        assert body["counts"] == {"applied": 2, "unchanged": 0, "conflict": 0, "not_found": 1, "not_candidate": 1, "invalid_id": 1}
        rejected = c.get("/api/v1/relations/candidates?status=rejected", headers=AUTH).json()
        assert {x["id"] for x in rejected["candidates"]} == {ids[0], ids[1]}
        assert all(x["review"]["note"] == "co-occurrence only" for x in rejected["candidates"])
        # the non-candidate relation is untouched
        rels = {r["id"]: r for r in c.get("/api/v1/relations?limit=1000", headers=AUTH).json()}
        assert rels[plain["id"]]["verification_state"] == "human_verified" and "review" not in (rels[plain["id"]].get("properties") or {})
        # all-invalid batch: no commit, no batch id
        none = c.post(BULK, json={"ids": [missing], "decision": "approve", "note": "x"}, headers=AUTH).json()
        assert none["batch_id"] is None and none["counts"]["not_found"] == 1


def test_candidates_expose_source_file_and_review_ui_is_bulk_capable():
    with client() as c:
        pending_ids(c)
        first = c.get("/api/v1/relations/candidates", headers=AUTH).json()["candidates"][0]
        assert first["source_file"] and first["source_file"].endswith("sion-map-production.json")
        page = c.get("/review").text
        for needle in ("/api/v1/relations/candidates/bulk", "필터 결과 전체 선택", "추천", "자동 적용되지 않", 'data-key="j"'):
            assert needle in page, needle
        # the hint is never wired to a decision call
        decisions = page[page.index("async function decide") : page.index("// ---- display-only")]
        assert "recommend(" not in decisions and "hint" not in decisions
