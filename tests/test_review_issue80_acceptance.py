"""Issue #80 remaining checklist / acceptance criteria.

* opposite-decision conflicts (approve -> reject, reject -> approve) and the explicit re-review path
* bulk ``batch_id`` + per-id outcomes in the batch log (outbox) and the verification report
* fixtures for human_verified / unverified / rejected with a projection regression test
* repeat approval is idempotent, rejected is excluded by default, unverified is shown with
  evidence and never auto-approved, reviewer/note/batch_id are preserved
* approval is documented (UI/API) as not replacing fact verification
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_api import models, schemas
from sion_api.main import create_app
from sion_graphrag.projection import build_custom_kg
from sion_graphrag.review_report import (
    AUDIT_REPORT_REVIEW_STATES,
    DEFAULT_REPORT_REVIEW_STATES,
    build_review_report,
)
from sqlalchemy import func, select
from test_review_bulk import AUTH, BULK, client, pending_ids

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "review_states_kg.json"
REPORT = "/api/v1/review/report"
FILTERS = {
    "verified": ["verified"],
    "unverified": ["unverified"],
    "rejected": ["rejected"],
    "default": list(DEFAULT_REPORT_REVIEW_STATES),
    "audit": list(AUDIT_REPORT_REVIEW_STATES),
}


# --- fixtures for all three review states ----------------------------------------------------


@pytest.fixture()
def fixture_app():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        ids = {}
        for key in data["entities"]:
            r = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Project", "name": key})
            assert r.status_code == 201, r.text
            ids[key] = r.json()["id"]
        for rel in data["relations"]:
            properties = {"candidate": True}
            if rel["review"]:
                properties["review"] = rel["review"]
            r = c.post("/api/v1/relations", json={
                "stable_key": rel["stable_key"], "source_entity_id": ids[rel["source"]],
                "target_entity_id": ids[rel["target"]], "relation_type_id": "RELATED_TO",
                "confidence": rel["confidence"], "verification_state": rel["verification_state"],
                "source_kind": "inferred", "properties": properties,
            })
            assert r.status_code == 201, r.text
            r = c.post("/api/v1/evidence", json={
                "relation_id": r.json()["id"], **rel["evidence"], "verification_state": rel["verification_state"],
            })
            assert r.status_code == 201, r.text
        yield app, data


def _weights(kg) -> dict[str, float]:
    return {r["source_id"].removeprefix("sion:relation:"): r["weight"] for r in kg["relationships"]}


@pytest.mark.parametrize("name", sorted(FILTERS))
def test_fixture_projection_regression_per_state(fixture_app, name):
    app, data = fixture_app
    with app.state.session_factory() as session:
        weights = _weights(build_custom_kg(session, review_states=FILTERS[name]))
    assert weights == pytest.approx(data["expected_weights"][name])


def test_fixture_unverified_is_projected_with_evidence_and_stays_unverified(fixture_app):
    app, _ = fixture_app
    with app.state.session_factory() as session:
        kg = build_custom_kg(session, review_states=DEFAULT_REPORT_REVIEW_STATES)
        state = session.scalar(select(models.Relation.verification_state).where(models.Relation.stable_key.like("rv:def:un%")))
    [chunk] = [c for c in kg["chunks"] if c["source_id"] == "sion:relation:rv:def:un|RELATED_TO|rv:class:wall"]
    assert "verification_state: unverified" in chunk["content"]
    assert "evidence: data/sources/fixture/un.json @ $.definitions[1] (unverified)" in chunk["content"]
    assert state == "unverified"  # projecting never promotes a candidate


def test_fixture_report_default_and_audit(fixture_app):
    app, data = fixture_app
    with app.state.session_factory() as session:
        default = build_review_report(session)
        audit = build_review_report(session, review_states=AUDIT_REPORT_REVIEW_STATES)
    assert default["fact_verification"] is False and "does not verify" in default["notice"]
    assert default["counts"] == {
        "human_verified": {"total": 1, "projected_under_policy": 1},
        "rejected": {"total": 1, "projected_under_policy": 0},
        "unverified": {"total": 1, "projected_under_policy": 1},
    }
    by_key = {r["stable_key"]: r for r in default["relations"]}
    assert set(by_key) == {"rv:def:hv|RELATED_TO|rv:class:wall", "rv:def:rj|RELATED_TO|rv:class:wall"}
    hv, rj = by_key["rv:def:hv|RELATED_TO|rv:class:wall"], by_key["rv:def:rj|RELATED_TO|rv:class:wall"]
    assert hv["projected_under_policy"] is True and hv["weight"] == pytest.approx(1.85)
    assert hv["review"]["reviewer"] == "fixture-reviewer" and hv["review"]["note"] == "checked against plan"
    assert hv["review"]["batch_id"] == data["relations"][0]["review"]["batch_id"]
    assert rj["projected_under_policy"] is False and rj["weight"] is None
    assert {b["batch_id"]: b["current_relations"] for b in default["batches"]} == {
        "11111111-1111-4111-8111-111111111111": ["rv:def:hv|RELATED_TO|rv:class:wall"],
        "22222222-2222-4222-8222-222222222222": ["rv:def:rj|RELATED_TO|rv:class:wall"],
    }
    assert audit["counts"]["rejected"] == {"total": 1, "projected_under_policy": 1}


# --- opposite decisions and the re-review path ------------------------------------------------


def _row(c: TestClient, rid: str) -> models.Relation:
    with c.app.state.session_factory() as s:
        row = s.get(models.Relation, uuid.UUID(rid))
        s.expunge(row)
        return row


@pytest.mark.parametrize("first,second", [("approve", "reject"), ("reject", "approve")])
def test_opposite_decision_is_a_conflict_and_keeps_the_first(first, second):
    with client() as c:
        rid = pending_ids(c)[0]
        url = f"/api/v1/relations/candidates/{rid}"
        assert c.post(f"{url}/{first}", json={"reviewer": "r1", "note": "first"}, headers=AUTH).status_code == 200
        before = _row(c, rid)

        per_item = c.post(f"{url}/{second}", json={"reviewer": "r2", "note": "second"}, headers=AUTH)
        assert per_item.status_code == 409
        bulk = c.post(BULK, json={"ids": [rid], "decision": second, "note": "second", "reviewer": "r2"}, headers=AUTH).json()
        [item] = bulk["results"]
        assert item["result"] == "conflict" and item["ok"] is False and item["batch_id"] is None
        assert bulk["batch_id"] is None and bulk["counts"]["applied"] == 0

        after = _row(c, rid)
        assert after.verification_state == before.verification_state == ("human_verified" if first == "approve" else "rejected")
        assert after.properties["review"] == before.properties["review"]
        assert after.properties["review"]["reviewer"] == "r1" and after.properties["review"]["note"] == "first"


def test_rereview_requires_note_keeps_history_and_never_deletes():
    with client() as c:
        rid = pending_ids(c)[0]
        url = f"/api/v1/relations/candidates/{rid}"
        with c.app.state.session_factory() as s:
            counts = (s.scalar(select(func.count()).select_from(models.Relation)), s.scalar(select(func.count()).select_from(models.Evidence)))

        first = c.post(BULK, json={"ids": [rid], "decision": "approve", "note": "looks right", "reviewer": "r1"}, headers=AUTH).json()
        batch_a = first["batch_id"]
        assert batch_a and first["results"][0]["batch_id"] == batch_a

        # re-review is explicit: a reopen with a non-blank note; the opposite decision cannot skip it
        assert c.post(f"{url}/reopen", json={}, headers=AUTH).status_code == 422
        assert c.post(f"{url}/reopen", json={"note": "  "}, headers=AUTH).status_code == 422
        assert c.post(f"{url}/reject", json={"note": "skip reopen"}, headers=AUTH).status_code == 409
        reopened = c.post(f"{url}/reopen", json={"note": "source plan revised", "reviewer": "r2"}, headers=AUTH)
        assert reopened.status_code == 200 and reopened.json()["status"] == "pending"

        second = c.post(BULK, json={"ids": [rid], "decision": "reject", "note": "revised plan", "reviewer": "r2"}, headers=AUTH).json()
        batch_b = second["batch_id"]
        assert second["results"][0]["result"] == "applied" and batch_b and batch_b != batch_a

        row = _row(c, rid)
        assert row.verification_state == "rejected"
        assert row.properties["review"]["batch_id"] == batch_b and row.properties["review"]["reviewer"] == "r2"
        [old] = row.properties["review_history"]
        assert old["decision"] == "approved" and old["reviewer"] == "r1" and old["note"] == "looks right"
        assert old["batch_id"] == batch_a and old["reverted_state"] == "human_verified"
        assert old["reopened_by"] == "r2" and old["reopen_note"] == "source plan revised"
        with c.app.state.session_factory() as s:
            assert (s.scalar(select(func.count()).select_from(models.Relation)), s.scalar(select(func.count()).select_from(models.Evidence))) == counts
            for ev in s.scalars(select(models.Evidence).where(models.Evidence.relation_id == uuid.UUID(rid))):
                assert ev.properties["review"]["batch_id"] == batch_b
                assert ev.properties["review_history"][0]["batch_id"] == batch_a

        report = c.get(REPORT, headers=AUTH).json()
        [entry] = [r for r in report["relations"] if r["stable_key"] == row.stable_key]
        assert entry["projected_under_policy"] is False  # rejected is excluded by default
        assert entry["review"]["batch_id"] == batch_b and entry["review_history"][0]["batch_id"] == batch_a
        batches = {b["batch_id"]: b for b in report["batches"]}
        assert batches[batch_a]["decision"] == "approved" and batches[batch_a]["current_relations"] == []
        assert batches[batch_a]["results"] == [{"id": rid, "result": "applied", "ok": True, "reason": None}]
        assert batches[batch_b]["decision"] == "rejected" and batches[batch_b]["current_relations"] == [row.stable_key]


# --- batch log + verification report ------------------------------------------------------


def test_bulk_batch_log_has_batch_id_and_per_id_outcomes():
    with client() as c:
        ids = pending_ids(c)
        assert c.post(BULK, json={"ids": ids[:1], "decision": "approve", "note": "first"}, headers=AUTH).status_code == 200
        payload = {"ids": [ids[0], ids[1], "not-a-uuid"], "decision": "approve", "note": "second", "reviewer": "khs"}
        body = c.post(BULK, json=payload, headers=AUTH).json()
        assert [r["result"] for r in body["results"]] == ["unchanged", "applied", "invalid_id"]

        with c.app.state.session_factory() as s:
            events = s.scalars(select(models.OutboxEvent).where(models.OutboxEvent.event_type == "review.batch_decided")
                               .order_by(models.OutboxEvent.created_at)).all()
        assert len(events) == 2
        event = events[-1]
        assert event.aggregate_type == "review_batch" and str(event.aggregate_id) == body["batch_id"]
        assert event.payload["batch_id"] == body["batch_id"] and event.payload["reviewer"] == "khs"
        assert event.payload["note"] == "second" and event.payload["counts"] == body["counts"]
        assert event.payload["results"] == [
            {"id": r["id"], "result": r["result"], "ok": r["ok"], "reason": r["reason"]} for r in body["results"]
        ]

        # a call that applies nothing has no batch and writes no event
        again = c.post(BULK, json=payload, headers=AUTH).json()
        assert again["batch_id"] is None and again["counts"]["applied"] == 0
        with c.app.state.session_factory() as s:
            assert s.scalar(select(func.count()).select_from(models.OutboxEvent)
                            .where(models.OutboxEvent.event_type == "review.batch_decided")) == 2

        report = c.get(REPORT, headers=AUTH).json()
        [batch] = [b for b in report["batches"] if b["batch_id"] == body["batch_id"]]
        assert batch["results"] == event.payload["results"] and batch["reviewer"] == "khs"


def test_repeat_bulk_approval_does_not_raise_weight():
    with client() as c:
        rid = pending_ids(c)[0]
        weights = []
        for _ in range(3):
            body = c.post(BULK, json={"ids": [rid], "decision": "approve", "note": "ok"}, headers=AUTH).json()
            report = c.get(REPORT, headers=AUTH).json()
            [entry] = [r for r in report["relations"] if r["review"]]
            weights.append(entry["weight"])
        assert body["results"][0]["result"] == "unchanged"
        assert weights[0] == weights[1] == weights[2] and weights[0] is not None


def test_import_never_auto_approves_and_shows_evidence():
    with client() as c:
        pending_ids(c)
        listed = c.get("/api/v1/relations/candidates?limit=1000", headers=AUTH).json()
        assert listed["counts"] == {"pending": 43, "approved": 0, "rejected": 0}
        assert all(x["status"] == "pending" and x["review"] is None for x in listed["candidates"])
        assert all(x["evidence_count"] >= 1 and x["evidence"] for x in listed["candidates"])
        report = c.get(REPORT, headers=AUTH).json()
        assert report["counts"]["unverified"]["total"] == report["counts"]["unverified"]["projected_under_policy"] == 43
        assert report["relations"] == [] and report["batches"] == []


def test_report_excludes_rejected_by_default_and_audit_flag():
    with client() as c:
        ids = pending_ids(c)
        assert c.post(BULK, json={"ids": ids[:2], "decision": "reject", "note": "weak"}, headers=AUTH).status_code == 200
        default = c.get(REPORT, headers=AUTH).json()
        audit = c.get(REPORT, params={"include_rejected": "true"}, headers=AUTH).json()
        assert default["counts"]["rejected"] == {"total": 2, "projected_under_policy": 0}
        assert audit["counts"]["rejected"] == {"total": 2, "projected_under_policy": 2}
        assert "rejected" not in default["projected_states"] and "rejected" in audit["projected_states"]
        assert c.get(REPORT).status_code == 401  # read:knowledge required


def test_report_is_paginated_and_filterable_by_batch():
    with client() as c:
        ids = pending_ids(c)
        first = c.post(BULK, json={"ids": ids[:3], "decision": "approve", "note": "a"}, headers=AUTH).json()
        second = c.post(BULK, json={"ids": ids[3:5], "decision": "reject", "note": "b"}, headers=AUTH).json()

        full = c.get(REPORT, headers=AUTH).json()
        assert full["relations_total"] == 5 and full["batches_total"] == 2
        assert [b["batch_id"] for b in full["batches"]] == [first["batch_id"], second["batch_id"]]

        page = c.get(REPORT, params={"limit": 2, "offset": 1}, headers=AUTH).json()
        assert page["limit"] == 2 and page["offset"] == 1
        assert page["relations_total"] == 5 and page["batches_total"] == 2
        assert [r["stable_key"] for r in page["relations"]] == [r["stable_key"] for r in full["relations"][1:3]]
        assert [b["batch_id"] for b in page["batches"]] == [second["batch_id"]]

        only = c.get(REPORT, params={"batch_id": second["batch_id"]}, headers=AUTH).json()
        assert only["relations_total"] == 2 and only["batches_total"] == 1
        assert {r["review"]["batch_id"] for r in only["relations"]} == {second["batch_id"]}
        assert len(only["batches"][0]["current_relations"]) == 2

        assert c.get(REPORT, params={"batch_id": "nope"}, headers=AUTH).json()["batches"] == []
        assert c.get(REPORT, params={"limit": 0}, headers=AUTH).status_code == 422
        assert c.get(REPORT, params={"limit": 1001}, headers=AUTH).status_code == 422


def test_report_matches_live_index_default_policy():
    with client() as c:
        report = c.get(REPORT, headers=AUTH).json()
        assert report["live_index_applies_policy"] is True
        assert "excludes rejected" in report["policy_notice"]
        audit = c.get(REPORT, params={"include_rejected": "true"}, headers=AUTH).json()
        assert audit["live_index_applies_policy"] is False


def test_bulk_ids_are_length_bounded_before_they_reach_the_batch_log():
    with client() as c:
        ids = pending_ids(c)
        r = c.post(BULK, json={"ids": [ids[0], "x" * 65], "decision": "approve", "note": "n"}, headers=AUTH)
        assert r.status_code == 422
        with c.app.state.session_factory() as s:
            assert s.scalar(select(func.count()).select_from(models.OutboxEvent)
                            .where(models.OutboxEvent.event_type == "review.batch_decided")) == 0


# --- approval does not replace fact verification (UI/API/docs) -----------------------------


def test_ui_api_and_docs_state_approval_is_not_fact_verification():
    page = (ROOT / "apps" / "web" / "review.html").read_text(encoding="utf-8")
    assert "사실 검증을 대신하지 않습니다" in page
    assert "not a fact verification" in (schemas.BulkCandidateDecision.model_json_schema()["description"])
    assert "does not verify the underlying fact" in " ".join(schemas.CandidateDecision.__doc__.split())
    assert "re-review" in schemas.CandidateReopen.__doc__
    assert "does not replace fact verification" in (ROOT / "docs" / "GRAPHRAG.md").read_text(encoding="utf-8")
    assert "not a fact verification" in (ROOT / "docs" / "SKETCHUP_KNOWLEDGE.md").read_text(encoding="utf-8")
