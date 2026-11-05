"""Issue #80 step 2: rejecting a /review candidate records ``rejected`` and keeps the row."""

from __future__ import annotations

import uuid

from sion_api import models
from sion_graphrag.projection import build_custom_kg
from sqlalchemy import func, select
from test_review_bulk import AUTH, BULK, client, pending_ids


def _counts(session):
    return (
        session.scalar(select(func.count()).select_from(models.Relation)),
        session.scalar(select(func.count()).select_from(models.Evidence)),
    )


def test_reject_keeps_row_and_evidence_with_rejected_state():
    with client() as c:
        ids = pending_ids(c)
        factory = c.app.state.session_factory
        with factory() as s:
            before = _counts(s)

        single = c.post(f"/api/v1/relations/candidates/{ids[0]}/reject", json={"reviewer": "khs", "note": "no evidence"}, headers=AUTH)
        assert single.status_code == 200 and single.json()["status"] == "rejected"
        bulk = c.post(BULK, json={"ids": ids[1:3], "decision": "reject", "note": "co-occurrence only"}, headers=AUTH)
        assert bulk.status_code == 200, bulk.text

        rejected_ids = {uuid.UUID(i) for i in ids[:3]}
        with factory() as s:
            assert _counts(s) == before  # nothing deleted
            rows = s.scalars(select(models.Relation).where(models.Relation.id.in_(rejected_ids))).all()
            assert len(rows) == 3
            for row in rows:
                assert row.verification_state == "rejected"
                assert row.properties["review"]["decision"] == "rejected"
                assert row.properties["review"]["previous_state"] == "unverified"
            for ev in s.scalars(select(models.Evidence).where(models.Evidence.relation_id.in_(rejected_ids))):
                assert ev.verification_state == "rejected"

        listed = c.get("/api/v1/relations/candidates?status=rejected", headers=AUTH).json()
        assert {x["id"] for x in listed["candidates"]} == set(ids[:3])
        assert listed["counts"] == {"pending": 40, "approved": 0, "rejected": 3}


def test_rejected_rows_compatible_with_review_state_filter():
    """Kept rejected rows are excluded by the #96 verified/unverified buckets and selectable as ``rejected``."""
    with client() as c:
        ids = pending_ids(c)
        assert c.post(BULK, json={"ids": ids[:2], "decision": "reject", "note": "weak"}, headers=AUTH).status_code == 200
        with c.app.state.session_factory() as s:
            total = len(build_custom_kg(s, review_states=None)["relationships"])
            rejected = build_custom_kg(s, review_states=["rejected"])["relationships"]
            unverified = build_custom_kg(s, review_states=["unverified"])["relationships"]
            verified = build_custom_kg(s, review_states=["verified"])["relationships"]
        assert len(rejected) == 2
        assert all("verification_state: rejected" in r["description"] for r in rejected)
        assert not any("verification_state: rejected" in r["description"] for r in unverified + verified)
        assert len(rejected) + len(unverified) + len(verified) == total
