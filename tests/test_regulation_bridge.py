"""Sion API -> ArchOntos rule evaluator (packages/regulation)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sion_api import regulation
from sion_api.main import create_app

needs_regulation = pytest.mark.skipif(
    not regulation.status()["available"], reason="needs the 'regulation' extra"
)

STAIR_RULE = {
    "applicability": {"conditions": [{">=": [{"var": "building.floor_count"}, 7]}]},
    "rule": {
        "if": {">=": [{"var": "stair.direct_count"}, 2]},
        "then": {"PASS": {"reason": "minimum satisfied"}},
        "else": {"FAIL": {"reason": "direct stairs missing", "required": 2, "actual": {"var": "stair.direct_count"}}},
    },
}


def _client() -> TestClient:
    return TestClient(create_app(database_url="sqlite://", auto_create_schema=True))


def test_status_endpoint_reports_extra():
    with _client() as c:
        body = c.get("/api/v1/regulation/status").json()
    assert body["engine"] == "archontos.rules.engine"
    assert isinstance(body["available"], bool)


@needs_regulation
def test_pass_fail_review_and_not_applicable():
    with _client() as c:
        def outcome(facts):
            r = c.post("/api/v1/regulation/evaluate", json={"rule": STAIR_RULE, "facts": facts})
            assert r.status_code == 200, r.text
            return r.json()["result"]

        assert outcome({"building": {"floor_count": 9}, "stair": {"direct_count": 2}})["outcome"] == "PASS"
        assert outcome({"building": {"floor_count": 9}, "stair": {"direct_count": 1}})["outcome"] == "FAIL"
        # fail-closed: a missing fact is REVIEW, never PASS/FAIL
        assert outcome({"building": {"floor_count": 9}})["outcome"] == "REVIEW"
        na = outcome({"building": {"floor_count": 3}, "stair": {"direct_count": 0}})
        assert na["applicable"] is False and na["outcome"] is None
        bad = c.post("/api/v1/regulation/evaluate", json={"rule": {"rule": {"if": {"nope": [1]}, "then": {"PASS": {}}}}, "facts": {}})
        assert bad.json()["result"]["outcome"] == "REVIEW"


@needs_regulation
def test_entity_properties_supply_facts():
    with _client() as c:
        entity = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "building:a",
                "entity_type_id": "Concept",
                "name": "Building A",
                "properties": {"building": {"floor_count": 12}, "stair": {"direct_count": 1}},
            },
        ).json()
        r = c.post("/api/v1/regulation/evaluate", json={"rule": STAIR_RULE, "entity_id": entity["id"]})
        assert r.json()["result"]["outcome"] == "FAIL"
        # request facts override entity properties (deep merge)
        r = c.post(
            "/api/v1/regulation/evaluate",
            json={"rule": STAIR_RULE, "entity_id": entity["id"], "facts": {"stair": {"direct_count": 2}}},
        )
        assert r.json()["result"]["outcome"] == "PASS"
        missing = c.post(
            "/api/v1/regulation/evaluate",
            json={"rule": STAIR_RULE, "entity_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert missing.status_code == 404


def test_unavailable_engine_returns_503(monkeypatch):
    def boom(*_args, **_kwargs):
        raise regulation.RegulationUnavailable("install the regulation extra")

    monkeypatch.setattr(regulation, "evaluate", boom)
    with _client() as c:
        r = c.post("/api/v1/regulation/evaluate", json={"rule": STAIR_RULE, "facts": {}})
    assert r.status_code == 503
