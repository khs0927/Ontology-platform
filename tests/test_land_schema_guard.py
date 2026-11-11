"""The parcel contract must be validated before deriving regulation facts."""

import asyncio
import copy
import json

import pytest
from sion_api import regulation
from sion_core import MissingExtra, contracts


@pytest.fixture
def valid_parcel():
    return {
        "query": "synthetic parcel",
        "parcel": {"administrative": {}, "point_wgs84": {"x": 127.0, "y": 37.5}},
        "zoning": {"use_zone": [], "use_district": [], "use_area": [], "land_transaction_permit": []},
        "district_plan": [], "urban_facility": [], "other_law_designations": [],
        "priority_delegation_hint": {"applies": False},
        "buildings": {"present": False, "count": 0}, "next_steps": [],
        "source": {"precision": "polygon"}, "layer_errors": [],
    }


def test_valid_schema_can_produce_confirmed_polygon_absence(valid_parcel):
    land = regulation.land_facts_checked(valid_parcel)["land"]
    assert land["in_development_restriction_zone"] is False


@pytest.mark.parametrize("change", ["missing_zoning_field", "wrong_zoning_type", "missing_layer_errors"])
def test_malformed_polygon_is_rejected_by_schema(valid_parcel, change):
    record = copy.deepcopy(valid_parcel)
    if change == "missing_zoning_field":
        del record["zoning"]["use_area"]
    elif change == "wrong_zoning_type":
        record["zoning"]["use_area"] = "not an array"
    else:
        del record["layer_errors"]
    with pytest.raises(ValueError, match="contract violated"):
        regulation.land_facts_checked(record)


@pytest.mark.parametrize("malformed", [False, True])
def test_missing_jsonschema_never_derives_facts(valid_parcel, monkeypatch, malformed):
    if malformed:
        del valid_parcel["zoning"]["use_area"]

    def unavailable(*args, **kwargs):
        raise MissingExtra("jsonschema", "test")

    monkeypatch.setattr(contracts, "errors", unavailable)
    with pytest.raises(ValueError, match="validation unavailable"):
        regulation.land_facts_checked(valid_parcel)


def test_api_missing_jsonschema_returns_422_without_evaluation(valid_parcel, monkeypatch):
    from sion_api.main import create_app

    def unavailable(*args, **kwargs):
        raise MissingExtra("jsonschema", "test")

    def must_not_evaluate(*args, **kwargs):
        pytest.fail("unvalidated facts reached the rule evaluator")

    monkeypatch.setattr(contracts, "errors", unavailable)
    monkeypatch.setattr(regulation, "evaluate", must_not_evaluate)
    app = create_app(database_url="sqlite://", auto_create_schema=True)

    async def request():
        body = json.dumps({"rule": {}, "land_parcel": valid_parcel}).encode()
        messages = []
        sent = False
        never = asyncio.Event()

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await never.wait()

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/api/v1/regulation/evaluate",
                 "raw_path": b"/api/v1/regulation/evaluate", "root_path": "", "query_string": b"",
                 "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
                 "client": ("127.0.0.1", 50000), "server": ("localhost", 80)}
        await asyncio.wait_for(app(scope, receive, send), timeout=10)
        return messages

    messages = asyncio.run(request())
    assert next(m["status"] for m in messages if m["type"] == "http.response.start") == 422
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    assert "validation unavailable" in json.loads(body)["detail"]


def test_route_rejects_missing_jsonschema_before_evaluation(valid_parcel, monkeypatch):
    from fastapi import HTTPException
    from sion_api.main import create_app
    from sion_api.schemas import RegulationEvaluate

    def unavailable(*args, **kwargs):
        raise MissingExtra("jsonschema", "test")

    def must_not_evaluate(*args, **kwargs):
        pytest.fail("unvalidated facts reached the rule evaluator")

    monkeypatch.setattr(contracts, "errors", unavailable)
    monkeypatch.setattr(regulation, "evaluate", must_not_evaluate)
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/v1/regulation/evaluate")
    with pytest.raises(HTTPException) as exc:
        endpoint(RegulationEvaluate(rule={}, land_parcel=valid_parcel), session=None)
    assert exc.value.status_code == 422
    assert "validation unavailable" in exc.value.detail
