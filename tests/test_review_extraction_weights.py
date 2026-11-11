"""Issue #80: /review decisions adjust later candidate ranking, and reopen removes the vote.

The multiplier is a fold of ``relation.updated`` events. It never overwrites
extracted confidence and never promotes a candidate to ``human_verified``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_api import models
from sion_api.main import create_app
from sion_graphrag.projection import relation_weight
from sion_ingestion.review_weights import (
    MAX_MULTIPLIER,
    MIN_MULTIPLIER,
    fold_extraction_ledger,
    relation_event_fields,
    weight_keys,
)
from sqlalchemy import select

RULE = "en:uses:forward"


class _Event:
    def __init__(self, id, aggregate_id, event_type, payload, created_at):
        self.id = id
        self.aggregate_id = aggregate_id
        self.event_type = event_type
        self.payload = payload
        self.created_at = created_at


def _vote(event_id, relation_id, effect, rev, when, keys=(f"rule:{RULE}",), review=None):
    return _Event(
        event_id,
        relation_id,
        "relation.updated",
        {
            "review_effect": effect,
            "review_rev": rev,
            "weight_keys": list(keys),
            "review": review or {"decision": "approved" if effect == "approve" else "rejected", "reviewer": "mus"},
        },
        when,
    )


def _ledger(events):
    return fold_extraction_ledger(events)


def test_weight_keys_prefer_rules_then_guideline_predicates():
    assert weight_keys({"rules": [" en:uses:forward ", "en:uses:forward"], "predicate": "applies_to_class"}) == [
        "rule:en:uses:forward",
        "guideline:applies_to_class",
    ]
    assert weight_keys({"predicate": "classified_as"}) == ["guideline:classified_as"]
    assert weight_keys({}) == []


def test_only_a_real_review_decision_produces_an_effect():
    assert relation_event_fields("human_verified", {}) == {}
    assert relation_event_fields("human_verified", {"candidate": True})["review_effect"] == "none"
    approved = relation_event_fields(
        "human_verified",
        {"candidate": True, "rules": [RULE], "review": {"decision": "approved", "reviewer": "mus"}, "review_rev": 1},
    )
    assert approved["review_effect"] == "approve"
    assert approved["weight_keys"] == [f"rule:{RULE}"]
    assert approved["review_rev"] == 1
    rejected = relation_event_fields(
        "rejected",
        {"candidate": True, "predicate": "applies_to_class", "review": {"decision": "rejected"}, "review_rev": 2},
    )
    assert rejected["review_effect"] == "reject"
    assert rejected["weight_keys"] == ["guideline:applies_to_class"]
    reopened = relation_event_fields(
        "unverified",
        {"candidate": True, "rules": [RULE], "review_history": [{"decision": "approved"}], "review_rev": 3},
    )
    assert reopened["review_effect"] == "none"


def test_fold_is_idempotent_reversible_and_capped():
    start = datetime(2026, 11, 11, tzinfo=timezone.utc)
    one = _vote("e1", "rel-1", "approve", 1, start)
    again = _vote("e2", "rel-1", "approve", 3, start + timedelta(minutes=2))
    undone = _vote("e0", "rel-1", "none", 2, start + timedelta(minutes=3))  # older rev must not beat e2
    created = _Event("c", "rel-1", "relation.created", {"review_effect": "approve", "review_rev": 9, "weight_keys": [f"rule:{RULE}"]}, start)
    ledger = _ledger([again, created, undone, one, one])
    thousandths, capped, approvals, rejections = ledger.contribution(f"rule:{RULE}")
    assert (thousandths, capped, len(approvals), len(rejections)) == (1050, False, 1, 0)
    assert approvals[0].event_id == "e2"
    assert _ledger([one, again, undone, created]).contribution(f"rule:{RULE}") == ledger.contribution(f"rule:{RULE}")

    votes = [_vote(f"e{i}", f"rel-{i}", "approve", 1, start + timedelta(seconds=i)) for i in range(7)]
    at_five = _ledger(votes[:5]).contribution(f"rule:{RULE}")
    at_six = _ledger(votes[:6]).contribution(f"rule:{RULE}")
    at_seven = _ledger(votes).contribution(f"rule:{RULE}")
    assert at_five[0] == 1250 and at_five[1] is False
    assert at_six[0] == at_seven[0] == 1250 and at_six[1] is True and at_seven[1] is True
    assert _ledger([_vote(f"r{i}", f"rej-{i}", "reject", 1, start) for i in range(6)]).contribution(f"rule:{RULE}")[0] == 750

    both = _vote("b", "rel-b", "approve", 1, start, keys=("rule:en:uses:forward", "guideline:applies_to_class"))
    mixed = _ledger([both])
    assert mixed.contribution("rule:en:uses:forward")[2][0].relation_id == "rel-b"
    assert mixed.contribution("guideline:applies_to_class")[2][0].relation_id == "rel-b"
    assert MIN_MULTIPLIER == 0.75 and MAX_MULTIPLIER == 1.25


def _client(tmp_path: Path | None = None) -> TestClient:
    roots = [tmp_path] if tmp_path is not None else []
    app = create_app(database_url="sqlite://", auto_create_schema=True, ingest_roots=roots)
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))


def _entity(c: TestClient, key: str, name: str) -> str:
    response = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Tool", "name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _candidate(c: TestClient, source: str, target: str, *, rules=None, predicate=None, confidence=0.6, key: str) -> str:
    properties = {"candidate": True, "extractor": "test"}
    if rules is not None:
        properties["rules"] = rules
    if predicate is not None:
        properties["predicate"] = predicate
    response = c.post(
        "/api/v1/relations",
        json={
            "stable_key": key,
            "source_entity_id": source,
            "target_entity_id": target,
            "relation_type_id": "USES",
            "confidence": confidence,
            "verification_state": "unverified",
            "source_kind": "inferred",
            "properties": properties,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _listed(c: TestClient, status: str = "all") -> dict:
    response = c.get("/api/v1/relations/candidates", params={"status": status, "limit": 1000})
    assert response.status_code == 200, response.text
    body = response.json()
    body["by_id"] = {row["id"]: row for row in body["candidates"]}
    return body


def _weight(row: dict) -> dict:
    return row["extraction_weight"]


def test_approval_reorders_later_candidates_and_reopen_undoes_it():
    with _client() as c:
        a = _entity(c, "tool:high", "High")
        b = _entity(c, "tool:low", "Low")
        donor_src = _entity(c, "tool:donor-src", "Donor source")
        donor_tgt = _entity(c, "tool:donor-tgt", "Donor target")
        high = _candidate(c, a, b, rules=["en:references:forward"], confidence=0.50, key="cand:high")
        low = _candidate(c, b, a, rules=[RULE], confidence=0.48, key="cand:low")
        donor = _candidate(c, donor_src, donor_tgt, rules=[RULE], confidence=0.30, key="cand:donor")

        before = _listed(c, "pending")
        assert [row["id"] for row in before["candidates"]] == [high, low, donor]
        assert before["extraction_weight_policy"]["auto_verifies"] is False
        assert _weight(before["by_id"][low])["multiplier"] == 1.0
        assert _weight(before["by_id"][low])["base_confidence"] == pytest.approx(0.48)

        approved = c.post(f"/api/v1/relations/candidates/{donor}/approve", json={"reviewer": "mus", "note": "rule holds"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["confidence"] == pytest.approx(0.30)
        assert approved.json()["verification_state"] == "human_verified"

        boosted = _listed(c, "pending")
        assert [row["id"] for row in boosted["candidates"]] == [low, high]
        low_weight = _weight(boosted["by_id"][low])
        assert low_weight["key"] == f"rule:{RULE}"
        assert low_weight["multiplier"] == pytest.approx(1.05)
        assert low_weight["score"] == pytest.approx(0.504)
        assert low_weight["approvals"] == 1 and low_weight["rejections"] == 0
        assert low_weight["auto_verifies"] is False and low_weight["reversible"] is True
        assert boosted["by_id"][low]["confidence"] == pytest.approx(0.48)
        assert boosted["by_id"][low]["verification_state"] == "unverified"
        assert low_weight["sources"][0]["relation_id"] == donor
        assert low_weight["sources"][0]["reviewer"] == "mus"
        assert low_weight["sources"][0]["note"] == "rule holds"
        assert low_weight["sources"][0]["event_id"]

        # A second approve is refused and cannot add another vote.
        assert c.post(f"/api/v1/relations/candidates/{donor}/approve", json={"reviewer": "mus"}).status_code == 409
        assert _weight(_listed(c)["by_id"][low])["multiplier"] == pytest.approx(1.05)

        reopened = c.post(f"/api/v1/relations/candidates/{donor}/reopen", json={"reviewer": "mus", "note": "look again"})
        assert reopened.status_code == 200, reopened.text
        restored = _listed(c, "pending")
        assert [row["id"] for row in restored["candidates"]] == [high, low, donor]
        assert _weight(restored["by_id"][low])["multiplier"] == 1.0
        assert _weight(restored["by_id"][low])["sources"] == []
        assert restored["by_id"][low]["verification_state"] == "unverified"

        # Approve, reopen, approve still counts as one vote.
        assert c.post(f"/api/v1/relations/candidates/{donor}/approve", json={"reviewer": "mus", "note": "again"}).status_code == 200
        assert _weight(_listed(c)["by_id"][low])["multiplier"] == pytest.approx(1.05)
        assert _weight(_listed(c)["by_id"][low])["approvals"] == 1


def test_rejection_lowers_the_score_until_reopen_and_does_not_delete():
    with _client() as c:
        src = _entity(c, "tool:s", "S")
        tgt = _entity(c, "tool:t", "T")
        other_s = _entity(c, "tool:os", "OS")
        other_t = _entity(c, "tool:ot", "OT")
        pending = _candidate(c, src, tgt, rules=[RULE], confidence=0.6, key="cand:pending")
        rejected = _candidate(c, other_s, other_t, rules=[RULE], confidence=0.6, key="cand:rejected")
        response = c.post(f"/api/v1/relations/candidates/{rejected}/reject", json={"reviewer": "mus", "note": "wrong verb"})
        assert response.status_code == 200, response.text
        body = _listed(c)
        assert body["by_id"][rejected]["verification_state"] == "rejected"
        assert body["by_id"][pending]["verification_state"] == "unverified"
        assert body["by_id"][pending]["confidence"] == pytest.approx(0.6)
        weight = _weight(body["by_id"][pending])
        assert weight["multiplier"] == pytest.approx(0.95)
        assert weight["score"] == pytest.approx(0.57)
        assert weight["rejections"] == 1 and weight["sources"][0]["decision"] == "rejected"
        assert c.post(f"/api/v1/relations/candidates/{rejected}/approve", json={"reviewer": "mus"}).status_code == 409
        assert _weight(_listed(c)["by_id"][pending])["multiplier"] == pytest.approx(0.95)
        assert c.post(f"/api/v1/relations/candidates/{rejected}/reopen", json={"note": "undo"}).status_code == 200
        assert _weight(_listed(c)["by_id"][pending])["multiplier"] == 1.0


def test_guideline_predicate_and_rule_votes_stay_on_their_own_keys():
    with _client() as c:
        nodes = [_entity(c, f"tool:g{i}", f"G{i}") for i in range(6)]
        guide = _candidate(c, nodes[0], nodes[1], predicate="applies_to_class", confidence=0.9, key="cand:guide")
        sibling = _candidate(c, nodes[2], nodes[3], predicate="applies_to_class", confidence=0.9, key="cand:guide-sibling")
        other = _candidate(c, nodes[4], nodes[5], rules=[RULE], confidence=0.9, key="cand:other-rule")
        assert c.post(f"/api/v1/relations/candidates/{guide}/approve", json={"reviewer": "mus", "note": "guideline link"}).status_code == 200
        body = _listed(c)
        guided = _weight(body["by_id"][sibling])
        assert guided["kind"] == "guideline" and guided["label"] == "applies_to_class"
        assert guided["multiplier"] == pytest.approx(1.05)
        assert body["by_id"][sibling]["verification_state"] == "unverified"
        assert body["by_id"][sibling]["confidence"] == pytest.approx(0.9)
        assert _weight(body["by_id"][other])["multiplier"] == 1.0
        assert _weight(body["by_id"][guide])["kind"] == "guideline"


def test_one_decision_votes_on_every_key_but_ranks_by_the_first_rule():
    with _client() as c:
        nodes = [_entity(c, f"tool:m{i}", f"M{i}") for i in range(6)]
        mixed = _candidate(
            c, nodes[0], nodes[1], rules=[RULE], predicate="applies_to_class", confidence=0.4, key="cand:mixed"
        )
        by_rule = _candidate(c, nodes[2], nodes[3], rules=[RULE], confidence=0.4, key="cand:by-rule")
        by_guide = _candidate(c, nodes[4], nodes[5], predicate="applies_to_class", confidence=0.4, key="cand:by-guide")
        assert c.post(f"/api/v1/relations/candidates/{mixed}/approve", json={"reviewer": "mus", "note": "both"}).status_code == 200
        body = _listed(c)
        assert _weight(body["by_id"][mixed])["key"] == f"rule:{RULE}"
        assert _weight(body["by_id"][by_rule])["multiplier"] == pytest.approx(1.05)
        assert _weight(body["by_id"][by_guide])["multiplier"] == pytest.approx(1.05)
        assert _weight(body["by_id"][by_guide])["sources"][0]["relation_id"] == mixed


def test_bulk_batch_id_is_on_the_weight_sources_and_dry_run_writes_nothing():
    with _client() as c:
        nodes = [_entity(c, f"tool:b{i}", f"B{i}") for i in range(6)]
        first = _candidate(c, nodes[0], nodes[1], rules=[RULE], confidence=0.4, key="cand:bulk-1")
        second = _candidate(c, nodes[2], nodes[3], rules=[RULE], confidence=0.4, key="cand:bulk-2")
        pending = _candidate(c, nodes[4], nodes[5], rules=[RULE], confidence=0.4, key="cand:bulk-pending")
        dry = c.post(
            "/api/v1/relations/candidates/bulk",
            json={"ids": [first], "decision": "approve", "note": "preview", "reviewer": "mus", "dry_run": True},
        )
        assert dry.status_code == 200, dry.text
        assert _weight(_listed(c)["by_id"][pending])["multiplier"] == 1.0

        live = c.post(
            "/api/v1/relations/candidates/bulk",
            json={"ids": [first, second], "decision": "approve", "note": "batch note", "reviewer": "mus"},
        )
        assert live.status_code == 200, live.text
        batch_id = live.json()["batch_id"]
        weight = _weight(_listed(c)["by_id"][pending])
        assert weight["multiplier"] == pytest.approx(1.1)
        assert weight["approvals"] == 2
        assert {source["batch_id"] for source in weight["sources"]} == {batch_id}
        assert {source["note"] for source in weight["sources"]} == {"batch note"}
        assert {source["reviewer"] for source in weight["sources"]} == {"mus"}
        assert weight["auto_verifies"] is False
        assert _listed(c)["by_id"][pending]["verification_state"] == "unverified"


def test_extra_approvals_do_not_pass_the_cap():
    with _client() as c:
        pending_s = _entity(c, "tool:cap-s", "Cap S")
        pending_t = _entity(c, "tool:cap-t", "Cap T")
        pending = _candidate(c, pending_s, pending_t, rules=[RULE], confidence=0.4, key="cand:cap-pending")
        donors = []
        for index in range(7):
            src = _entity(c, f"tool:cap-src-{index}", f"Cap src {index}")
            tgt = _entity(c, f"tool:cap-tgt-{index}", f"Cap tgt {index}")
            donors.append(_candidate(c, src, tgt, rules=[RULE], confidence=0.2, key=f"cand:cap-{index}"))
        for index, donor in enumerate(donors):
            assert c.post(f"/api/v1/relations/candidates/{donor}/approve", json={"reviewer": "mus", "note": str(index)}).status_code == 200
            weight = _weight(_listed(c)["by_id"][pending])
            if index < 4:
                assert weight["capped"] is False
            else:
                assert weight["multiplier"] == pytest.approx(MAX_MULTIPLIER)
                assert weight["capped"] is (index >= 5)
        assert _weight(_listed(c)["by_id"][pending])["approvals"] == 7
        assert _listed(c)["by_id"][pending]["verification_state"] == "unverified"
        assert _listed(c)["by_id"][pending]["confidence"] == pytest.approx(0.4)


def test_direct_human_verified_facts_do_not_vote_and_events_carry_the_audit_fields():
    with _client() as c:
        src = _entity(c, "tool:fact-s", "Fact S")
        tgt = _entity(c, "tool:fact-t", "Fact T")
        pending_s = _entity(c, "tool:pend-s", "Pend S")
        pending_t = _entity(c, "tool:pend-t", "Pend T")
        fact = c.post(
            "/api/v1/relations",
            json={
                "stable_key": "fact:direct",
                "source_entity_id": src,
                "target_entity_id": tgt,
                "relation_type_id": "USES",
                "confidence": 1,
                "verification_state": "human_verified",
                "source_kind": "asserted",
                "properties": {},
            },
        )
        assert fact.status_code == 201, fact.text
        pending = _candidate(c, pending_s, pending_t, rules=[RULE], confidence=0.55, key="cand:untouched")
        assert _weight(_listed(c)["by_id"][pending])["multiplier"] == 1.0

        events = c.get("/api/v1/outbox", params={"limit": 1000}).json()
        fact_created = next(event for event in events if event["aggregate_id"] == fact.json()["id"] and event["event_type"] == "relation.created")
        assert "review_effect" not in fact_created["payload"]
        created = next(event for event in events if event["aggregate_id"] == pending and event["event_type"] == "relation.created")
        assert created["payload"]["review_effect"] == "none"
        assert created["payload"]["weight_keys"] == [f"rule:{RULE}"]

        assert c.post(f"/api/v1/relations/candidates/{pending}/approve", json={"reviewer": "mus", "note": "ok"}).status_code == 200
        updated = [
            event
            for event in c.get("/api/v1/outbox", params={"limit": 1000}).json()
            if event["aggregate_id"] == pending and event["event_type"] == "relation.updated"
        ]
        assert len(updated) == 1
        assert updated[0]["payload"]["review_effect"] == "approve"
        assert updated[0]["payload"]["review"]["reviewer"] == "mus"
        assert updated[0]["payload"]["review"]["note"] == "ok"
        assert updated[0]["payload"]["review_rev"] == 1


def test_future_extraction_keeps_base_confidence_and_records_the_weight(tmp_path):
    doc_one = tmp_path / "one.md"
    doc_two = tmp_path / "two.md"
    doc_one.write_text("Alpha Widget uses Beta Gadget.\n", encoding="utf-8")
    doc_two.write_text("Gamma Tool uses Delta Service.\n", encoding="utf-8")
    with _client(tmp_path) as c:
        _entity(c, "tool:alpha-widget", "Alpha Widget")
        _entity(c, "tool:beta-gadget", "Beta Gadget")
        _entity(c, "tool:gamma-tool", "Gamma Tool")
        _entity(c, "tool:delta-service", "Delta Service")
        first = c.post("/api/v1/extract/relations", json={"paths": [str(doc_one)]})
        assert first.status_code == 200, first.text
        assert first.json()["verification_state"] == "unverified"
        assert first.json()["candidates_created"] == 1
        listed = _listed(c)
        original = next(iter(listed["by_id"].values()))
        assert original["confidence"] == pytest.approx(0.6)
        assert _weight(original)["multiplier"] == 1.0
        assert c.post(
            f"/api/v1/relations/candidates/{original['id']}/approve",
            json={"reviewer": "mus", "note": "verb is explicit"},
        ).status_code == 200

        second = c.post("/api/v1/extract/relations", json={"paths": [str(doc_two)]})
        assert second.status_code == 200, second.text
        assert second.json()["candidates_created"] == 1
        assert second.json()["verification_state"] == "unverified"
        created_id = second.json()["candidate_ids"][0]
        fresh = c.get(f"/api/v1/relations/candidates/{created_id}").json()
        assert fresh["verification_state"] == "unverified"
        assert fresh["confidence"] == pytest.approx(0.6)
        assert {row["verification_state"] for row in fresh["evidence"]} == {"unverified"}
        assert fresh["evidence"]
        assert all(row["confidence"] == pytest.approx(0.6) for row in fresh["evidence"])
        weight = _weight(fresh)
        assert weight["score"] == pytest.approx(0.63)
        assert weight["multiplier"] == pytest.approx(1.05)
        assert weight["base_confidence"] == pytest.approx(0.6)
        assert weight["auto_verifies"] is False
        assert weight["snapshot_matches_live"] is True
        assert weight["recorded_at_extraction"]["multiplier"] == pytest.approx(1.05)
        assert weight["sources"][0]["relation_id"] == original["id"]

        with c.app.state.session_factory() as session:
            row = session.get(models.Relation, uuid.UUID(created_id))
            assert row.confidence == pytest.approx(0.6)
            assert row.verification_state == "unverified"
            assert relation_weight(row.confidence, row.verification_state) == pytest.approx(1.6)
            stored = row.properties["extraction_weight"]
            assert stored["auto_verifies"] is False
            assert stored["score"] == pytest.approx(0.63)

        assert c.post(
            f"/api/v1/relations/candidates/{original['id']}/reopen",
            json={"note": "the vote should drop"},
        ).status_code == 200
        after = c.get(f"/api/v1/relations/candidates/{created_id}").json()
        assert after["confidence"] == pytest.approx(0.6)
        assert after["verification_state"] == "unverified"
        assert _weight(after)["multiplier"] == 1.0
        assert _weight(after)["recorded_at_extraction"]["multiplier"] == pytest.approx(1.05)
        assert _weight(after)["snapshot_matches_live"] is False


def test_review_page_shows_the_weight_without_applying_it():
    page = Path(__file__).resolve().parents[1].joinpath("apps/web/review.html").read_text(encoding="utf-8")
    assert "사실 검증을 대신하지 않습니다" in page
    assert "자동 승인하지 않습니다" in page
    assert "되돌리기는 그 배수를 취소합니다" in page
    assert "function weightNote" in page
    decide = page[page.index("async function decide") : page.index("// ---- display-only")]
    assert "extraction_weight" not in decide
    assert "weightNote" not in decide


def test_ledger_query_ignores_unrelated_relation_updates():
    """A non-candidate update must not be required for the fold, and a candidate update is."""
    with _client() as c:
        src = _entity(c, "tool:q-s", "QS")
        tgt = _entity(c, "tool:q-t", "QT")
        _candidate(c, src, tgt, rules=[RULE], confidence=0.2, key="cand:query")
        with c.app.state.session_factory() as session:
            events = session.scalars(select(models.OutboxEvent).where(models.OutboxEvent.event_type == "relation.updated")).all()
            assert events == []
            created = session.scalars(select(models.OutboxEvent).where(models.OutboxEvent.event_type == "relation.created")).all()
            assert any((event.payload or {}).get("review_effect") == "none" for event in created)
            assert fold_extraction_ledger(created).votes == {}
