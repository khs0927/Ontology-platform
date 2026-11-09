"""Fail-closed handling of parcel overlay errors at the Sion/ArchOntos boundary."""

import pytest
from sion_api import regulation


@pytest.fixture
def parcel():
    return {
        "query": "synthetic parcel",
        "parcel": {"administrative": {}, "point_wgs84": {"x": 127.0, "y": 37.5}},
        "zoning": {"use_zone": [], "use_district": [], "use_area": [], "land_transaction_permit": []},
        "district_plan": [],
        "urban_facility": [],
        "other_law_designations": [],
        "priority_delegation_hint": {"applies": False},
        "buildings": {"present": False, "count": 0},
        "next_steps": [],
        "source": {"precision": "polygon"},
        "layer_errors": [],
    }


@pytest.mark.parametrize("layer", ["LT_C_UNKNOWN123", "?", "", "LT_C_UQ999"])
def test_unknown_error_withholds_all_negative_overlay_facts(parcel, layer):
    parcel["layer_errors"] = [{"layer": layer, "error_code": "TIMEOUT"}]
    land = regulation.facts_from_land_parcel(parcel)["land"]
    negatives = {
        "has_use_zone_hit", "use_zones", "has_use_district", "use_districts", "has_use_area",
        "use_areas", "in_development_restriction_zone", "land_transaction_permit", "in_district_plan",
        "district_plan_names", "urban_facility_overlap", "has_other_law_designation", "other_law_names",
        "priority_delegation",
    }
    assert negatives.isdisjoint(land)
    assert negatives <= set(land["unverified"])


@pytest.mark.parametrize("layer,affected", [
    ("LT_C_UPISUQ153", "urban_facility_overlap"),
    ("LT_C_AGRIXUE101", "has_other_law_designation"),
])
def test_known_failure_withholds_only_affected_family(parcel, layer, affected):
    parcel["layer_errors"] = [{"layer": layer, "error_code": "TIMEOUT"}]
    land = regulation.facts_from_land_parcel(parcel)["land"]
    assert affected not in land and affected in land["unverified"]
    assert land["has_use_district"] is False


def test_unknown_failure_keeps_positive_hits_and_marks_partial_lists(parcel):
    parcel["zoning"]["use_district"] = [{"layer": "LT_C_UQ121", "name": "landscape"}]
    parcel["layer_errors"] = [{"layer": "LT_C_UNKNOWN123", "error_code": "TIMEOUT"}]
    land = regulation.facts_from_land_parcel(parcel)["land"]
    assert land["has_use_district"] is True
    assert land["use_districts"] == ["landscape"]
    assert "use_districts" in land["unverified"]
    assert "in_development_restriction_zone" not in land


def test_error_free_polygon_and_point_have_distinct_absence_semantics(parcel):
    polygon = regulation.facts_from_land_parcel(parcel)["land"]
    assert polygon["in_development_restriction_zone"] is False
    parcel["source"]["precision"] = "point"
    point = regulation.facts_from_land_parcel(parcel)["land"]
    assert "in_development_restriction_zone" not in point
    assert "in_development_restriction_zone" in point["unverified"]


def test_unknown_layer_cannot_produce_a_pass_for_unverified_absence(parcel):
    parcel["layer_errors"] = [{"layer": "LT_C_UNKNOWN123", "error_code": "TIMEOUT"}]
    facts = regulation.facts_from_land_parcel(parcel)
    rule = {"rule": {"if": {"==": [{"var": "land.in_development_restriction_zone"}, False]},
                     "then": {"PASS": {"reason": "no restriction"}},
                     "else": {"FAIL": {"reason": "restriction"}}}}
    assert regulation.evaluate(rule, facts)["outcome"] == "REVIEW"


def test_checked_unknown_layer_is_refused_before_fact_extraction(parcel, monkeypatch):
    parcel["layer_errors"] = [{"layer": "LT_C_UNKNOWN123", "error_code": "TIMEOUT"}]

    def must_not_extract(*args, **kwargs):
        pytest.fail("unknown layer errors must not reach fact extraction")

    monkeypatch.setattr(regulation, "facts_from_land_parcel", must_not_extract)
    with pytest.raises(ValueError, match="unknown layer error"):
        regulation.land_facts_checked(parcel)


def test_route_unknown_layer_is_refused_before_rule_evaluation(parcel, monkeypatch):
    from fastapi import HTTPException
    from sion_api.main import create_app
    from sion_api.schemas import RegulationEvaluate

    parcel["layer_errors"] = [{"layer": "LT_C_UNKNOWN123", "error_code": "TIMEOUT"}]

    def must_not_evaluate(*args, **kwargs):
        pytest.fail("unknown layer errors must not reach the rule evaluator")

    monkeypatch.setattr(regulation, "evaluate", must_not_evaluate)
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/v1/regulation/evaluate")
    with pytest.raises(HTTPException) as exc:
        endpoint(RegulationEvaluate(rule={}, land_parcel=parcel), session=None)
    assert exc.value.status_code == 422
    assert "unknown layer error" in exc.value.detail


def test_api_unknown_layer_stops_before_rule_evaluation(parcel, monkeypatch):
    from fastapi.testclient import TestClient
    from sion_api.main import create_app

    parcel["layer_errors"] = [{"layer": "LT_C_UNKNOWN123", "error_code": "TIMEOUT"}]
    def must_not_evaluate(*args, **kwargs):
        pytest.fail("unknown layer errors must not reach the rule evaluator")

    monkeypatch.setattr(regulation, "evaluate", must_not_evaluate)
    rule = {"rule": {"if": {"==": [{"var": "land.in_development_restriction_zone"}, False]},
                     "then": {"PASS": {"reason": "no restriction"}},
                     "else": {"FAIL": {"reason": "restriction"}}}}
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True),
                    base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = client.post("/api/v1/regulation/evaluate", json={"rule": rule, "land_parcel": parcel})
    assert response.status_code == 422, response.text
    assert "unknown layer error" in response.json()["detail"]
