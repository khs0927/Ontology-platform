"""Fast /review sitting: queues, inline basis, per-item compare-and-set. Nothing is auto-approved."""

from __future__ import annotations

import json
from collections import Counter

from sion_api.review import QUEUE_MAP, QUEUE_SKETCHUP_CLASS, QUEUE_WORKFLOW, review_queue
from test_review_bulk import AUTH, BULK, ROOT, client

MAP_EXPORT = ROOT / "data" / "bootstrap" / "sion-map-export.json"
SKETCHUP_EXPORT = ROOT / "data" / "bootstrap" / "sketchup-0914-meeting.json"
CLASSIFICATION = ROOT / "data" / "sources" / "sketchup" / "0914-meeting" / "classification.json"
PAGE = ROOT / "apps" / "web" / "review.html"


def _queue(edge: dict) -> str:
    props = edge.get("properties") or {}
    provenance = props.get("provenance") if isinstance(props.get("provenance"), dict) else {}
    return review_queue(
        props,
        source_file=provenance.get("source_file"),
        source_key=edge.get("source_stable_key"),
        target_key=edge.get("target_stable_key"),
    )


def test_review_queue_labels_are_display_only():
    assert review_queue({"predicate": "classified_as"}, source_key="map:x") == QUEUE_SKETCHUP_CLASS
    assert review_queue({"predicate": "applies_to_class"}) == QUEUE_WORKFLOW
    assert review_queue({"predicate": "cites_model_evidence"}) == QUEUE_WORKFLOW
    assert review_queue({"predicate": "derived_from_grouping_probe"}) == QUEUE_WORKFLOW
    assert review_queue({"provenance": {"source_file": "sion-map-production.json"}}) == QUEUE_MAP
    assert review_queue({}, source_key="map:sion-production:core-gpo") == QUEUE_MAP
    assert review_queue({"predicate": "on_level"}) == "other"


def test_committed_backlog_files_stay_unverified():
    """The sitting UI must not be fed by flipping verification_state inside data files."""
    classification = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    assignments = classification["assignments"]
    assert len(assignments) == 214
    assert all(item["basis_ko"].strip() and "verification_state" not in item for item in assignments)

    sketchup = json.loads(SKETCHUP_EXPORT.read_text(encoding="utf-8"))
    candidates = [edge for edge in sketchup["edges"] if (edge.get("properties") or {}).get("candidate")]
    counts = Counter(_queue(edge) for edge in candidates)
    assert counts[QUEUE_SKETCHUP_CLASS] == 214
    assert counts[QUEUE_WORKFLOW] == 844
    assert counts[QUEUE_MAP] == 0
    classified = [edge for edge in candidates if (edge.get("properties") or {}).get("predicate") == "classified_as"]
    assert len(classified) == 214
    assert {edge["verification_state"] for edge in classified} == {"unverified"}

    exported = json.loads(MAP_EXPORT.read_text(encoding="utf-8"))
    assert len(exported["edges"]) == 43
    assert {edge["verification_state"] for edge in exported["edges"]} == {"unverified"}
    assert Counter(_queue(edge) for edge in exported["edges"])[QUEUE_MAP] == 43


def test_map_candidates_are_queued_without_being_verified():
    with client() as api:
        response = api.post(
            "/api/v1/import/graph-export",
            json={"path": str(MAP_EXPORT), "expected_node_count": 31, "expected_edge_count": 43},
            headers=AUTH,
        )
        assert response.status_code == 200, response.text
        first = api.get("/api/v1/relations/candidates?limit=1000", headers=AUTH).json()
        second = api.get("/api/v1/relations/candidates?limit=1000", headers=AUTH).json()
        assert first["total"] == 43 and first["counts"] == {"pending": 43, "approved": 0, "rejected": 0}
        assert second["counts"] == first["counts"]
        assert {row["queue"] for row in first["candidates"]} == {QUEUE_MAP}
        assert all(row["verification_state"] == "unverified" and row["version"] == 0 for row in first["candidates"])
        assert all(row["basis_ko"] is None and row["source"]["description"] for row in first["candidates"])
        assert {row["version"] for row in second["candidates"]} == {0}


def _candidate(api, *, key: str, source: str, target: str, predicate: str, confidence, basis: str | None, source_kind: str):
    properties = {"candidate": True, "predicate": predicate, "extractor": "test"}
    if basis is not None:
        properties["basis_ko"] = basis
    created = api.post(
        "/api/v1/relations",
        json={
            "stable_key": key,
            "source_entity_id": source,
            "target_entity_id": target,
            "relation_type_id": "IMPLEMENTS",
            "confidence": confidence,
            "verification_state": "unverified",
            "source_kind": source_kind,
            "properties": properties,
        },
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_basis_survives_human_decision_and_bulk_cas_is_per_item():
    with client() as api:
        long_desc = "가" * 400
        source = api.post(
            "/api/v1/entities",
            json={"stable_key": "su:def:deck", "entity_type_id": "Concept", "name": "그룹#3", "description": long_desc},
            headers=AUTH,
        ).json()
        target = api.post(
            "/api/v1/entities",
            json={"stable_key": "su:class:parking-deck", "entity_type_id": "Concept", "name": "parking-deck", "description": "주차장 데크"},
            headers=AUTH,
        ).json()
        other = api.post(
            "/api/v1/entities",
            json={"stable_key": "su:guide:group", "entity_type_id": "Document", "name": "그룹 지침", "description": "그룹으로 묶는 단계"},
            headers=AUTH,
        ).json()
        fresh = _candidate(
            api,
            key="su:def:deck:IMPLEMENTS:su:class:parking-deck",
            source=source["id"],
            target=target["id"],
            predicate="classified_as",
            confidence=0.6,
            basis="그룹 재질 [Polished Concrete New], 경사면 다수",
            source_kind="inferred",
        )
        stale = _candidate(
            api,
            key="su:guide:group:IMPLEMENTS:su:class:parking-deck",
            source=other["id"],
            target=target["id"],
            predicate="applies_to_class",
            confidence=0.9,
            basis=None,
            source_kind="inferred",
        )
        evidence = api.post(
            "/api/v1/evidence",
            json={
                "relation_id": fresh,
                "source_uri": "file:///data/sources/sketchup/0914-meeting/classification.json",
                "source_locator": "$.assignments[1]",
                "properties": {"excerpt": "경사면과 수평 바닥"},
            },
            headers=AUTH,
        )
        assert evidence.status_code == 201, evidence.text

        listed = api.get("/api/v1/relations/candidates?status=all&limit=1000", headers=AUTH).json()
        by_id = {row["id"]: row for row in listed["candidates"]}
        assert by_id[fresh]["queue"] == QUEUE_SKETCHUP_CLASS
        assert by_id[fresh]["basis_ko"] == "그룹 재질 [Polished Concrete New], 경사면 다수"
        assert by_id[fresh]["predicate"] == "classified_as"
        assert by_id[fresh]["verification_state"] == "unverified" and by_id[fresh]["version"] == 0
        assert by_id[fresh]["source"]["description"].endswith("…") and len(by_id[fresh]["source"]["description"]) == 280
        assert by_id[fresh]["evidence"][0]["excerpt"] == "경사면과 수평 바닥"
        assert by_id[stale]["queue"] == QUEUE_WORKFLOW and by_id[stale]["basis_ko"] is None
        detail = api.get(f"/api/v1/relations/candidates/{fresh}", headers=AUTH).json()
        assert detail["basis_ko"] == by_id[fresh]["basis_ko"] and detail["evidence_count"] == 1

        opened = api.post(f"/api/v1/relations/candidates/{stale}/approve", json={"note": "once", "expected_version": 0}, headers=AUTH)
        assert opened.status_code == 200, opened.text
        reopened = api.post(
            f"/api/v1/relations/candidates/{stale}/reopen",
            json={"note": "다시 본다", "expected_version": 1},
            headers=AUTH,
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["status"] == "pending" and reopened.json()["version"] == 2

        body = api.post(
            BULK,
            json={
                "ids": [stale, fresh],
                "decision": "approve",
                "note": "클래스 근거를 읽고 승인",
                "reviewer": "owner",
                "expected_versions": {stale: 0, fresh: 0},
            },
            headers=AUTH,
        ).json()
        results = {row["id"]: row for row in body["results"]}
        assert results[stale]["result"] == "conflict" and results[stale]["ok"] is False and results[stale]["version"] == 2
        assert results[fresh]["result"] == "applied" and results[fresh]["ok"] is True and results[fresh]["version"] == 1
        stale_row = api.get(f"/api/v1/relations/candidates/{stale}", headers=AUTH).json()
        fresh_row = api.get(f"/api/v1/relations/candidates/{fresh}", headers=AUTH).json()
        assert stale_row["status"] == "pending" and stale_row["version"] == 2
        assert fresh_row["verification_state"] == "human_verified" and fresh_row["version"] == 1
        assert fresh_row["basis_ko"] == "그룹 재질 [Polished Concrete New], 경사면 다수"
        assert fresh_row["confidence"] == 0.6
        assert fresh_row["evidence"][0]["excerpt"] == "경사면과 수평 바닥"


def test_review_page_keeps_decisions_on_explicit_actions():
    page = PAGE.read_text(encoding="utf-8")
    for needle in (
        "필터 결과 전체 선택",
        "자동 적용되지 않",
        "사실 검증을 대신하지 않습니다",
        "보기만 바꿉니다",
        'data-key="j"',
        'data-key="n"',
        'data-key="f"',
        "출발 노드",
        "도착 노드",
        "한 건씩",
        "SketchUp 분류",
        "basis_ko",
        "review_rev",
        "expected_versions",
        'id="conflicts"',
        'id="fqueue"',
        'id="fconfMax"',
        'id="progressText"',
        "/api/v1/relations/candidates/bulk",
    ):
        assert needle in page, needle
    decisions = page[page.index("async function decide") : page.index("// ---- display-only")]
    assert "recommend(" not in decisions and "hint" not in decisions
    assert "expected_version" in decisions and "expected_versions" in decisions
    queues = page[page.index('$("queues").addEventListener') : page.index('$("confPresets").addEventListener')]
    assert "decide(" not in queues and "bulk(" not in queues
    load = page[page.index("async function load") :]
    assert "decide(" not in load and "bulk(" not in load
