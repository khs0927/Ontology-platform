"""Regression tests for review findings on claims versus collected facts.

Policy under test (framework plan sections 7 and 16): a caller's claim never overrides, fills or
resolves a collected fact; collection-only paths are resolved only by evidenced server-side facts;
rule inputs are bound per subject; NOT_APPLICABLE and skipped coverage need an evidenced basis on
the deciding path. All values are synthetic fixtures.
"""

# ruff: noqa: E402

from __future__ import annotations

from typing import Any

import pytest

# The minimal ".[test]" install has no archontos/greenlet; skip like test_review_scenarios.
pytest.importorskip("sion_regulation.review.workflow", exc_type=ImportError)

from sion_regulation.review.model import Applicability
from sion_regulation.review.rase import FactBinding
from test_review_scenarios import (
    DAY,
    NOW,
    ChecklistItem,
    ChecklistProfile,
    Clause,
    Fact,
    FactStatus,
    FactStore,
    LegalCatalog,
    Provision,
    ProvisionTarget,
    assess,
    candidate,
    catalog_with,
    client_fact_problems,
    default_profile,
    evidence,
    fact,
    facts_from_land_record,
    plan,
    proposal,
    ref,
    request,
    rule,
    to_rule_facts,
    version,
    workflow_with,
)


def claim(path: str, value: Any, subject: str = "p1", **extra: Any) -> Fact:
    return fact(
        path,
        value,
        subject,
        status=FactStatus.ASSERTED,
        method=extra.pop("method", "user_claim"),
        evidence_ids=[],
        fact_id=extra.pop("fact_id", f"claim:{subject}:{path}"),
        **extra,
    )


# ------------------------------------------------------------------ rule input binding


def _slope_flow(**extra: Any) -> Any:
    requirement = Clause(fact_path="land.slope", operator="<=", value=15)
    return workflow_with(
        rules=[rule(requirement=requirement, **extra)],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],
    )


def test_project_subject_claim_does_not_overwrite_parcel_record() -> None:
    flow = _slope_flow()
    official = [fact("land.flag", True), fact("land.slope", 20, fact_id="slope-official")]
    baseline = flow.start_review(request(facts=official))
    assert baseline["rule_evaluations"][0]["outcome"] == "FAIL"

    other = claim("land.slope", 10, subject="proj-1")
    assert client_fact_problems([other]) == []
    output = flow.start_review(
        request(facts=[*official, other], the_proposal=proposal(revision="r2"))
    )
    evaluation = output["rule_evaluations"][0]
    assert evaluation["outcome"] == "REVIEW"
    assert output["summary"]["legacy_status"] != "permitted"


def test_to_rule_facts_omits_a_path_held_by_two_subjects() -> None:
    store = FactStore()
    store.add(fact("land.slope", 20))
    store.add(claim("land.slope", 10, subject="proj-1"))
    facts, used, missing = to_rule_facts(store, ["p1", "proj-1"], DAY)
    assert "slope" not in facts.get("land", {})
    assert "land.slope" in missing and used == []


def test_claim_cannot_set_a_rase_exception_flag() -> None:
    flow = _slope_flow(exceptions=[Clause(fact_path="land.exempt", operator="==", value=True)])
    facts = [fact("land.flag", True), fact("land.slope", 20), claim("land.exempt", True)]
    output = flow.start_review(request(facts=facts))
    assert output["rule_evaluations"][0]["outcome"] != "PASS"
    assert output["summary"]["legacy_status"] != "permitted"


def test_fact_binding_allowed_methods_are_enforced() -> None:
    binding = FactBinding(path="building.height", allowed_methods=["official_record"])
    flow = workflow_with(
        rules=[rule(fact_bindings=[binding])],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],
    )
    observed = fact("building.height", 10, subject="proj-1", unit="m", method="design_observed")
    output = flow.start_review(request(facts=[fact("land.flag", True), observed]))
    assert output["rule_evaluations"][0]["outcome"] == "REVIEW"

    official = fact("building.height", 10, subject="proj-1", unit="m")
    accepted = flow.start_review(
        request(facts=[fact("land.flag", True), official], the_proposal=proposal(revision="r2"))
    )
    assert accepted["rule_evaluations"][0]["outcome"] == "PASS"


def test_fact_binding_sources_are_enforced() -> None:
    binding = FactBinding(path="building.height", sources=["korean-land-mcp"])
    flow = workflow_with(
        rules=[rule(fact_bindings=[binding])],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],  # provider "fixture", not the bound source
    )
    height = fact("building.height", 10, subject="proj-1", unit="m")
    output = flow.start_review(request(facts=[fact("land.flag", True), height]))
    assert output["rule_evaluations"][0]["outcome"] == "REVIEW"


# ------------------------------------------------------------------ collected unknowns


def test_claims_do_not_fill_collected_unknowns() -> None:
    record = {"parcel": {"pnu": "p1", "jimok": "답"}, "source": {"precision": "point"}}
    collected, _ = facts_from_land_record(record, NOW, subject="p1")
    store = FactStore()
    for item in collected:
        store.add(item)
    claims = [claim("designation.query_complete", True), claim("legal.is_farmland", False)]
    assert all(client_fact_problems([item]) for item in claims)
    for item in claims:  # defence in depth: added anyway, they must not resolve the path
        store.add(item)
    for path in ("designation.query_complete", "legal.is_farmland"):
        assert store.current(path, "p1", DAY).status is FactStatus.UNKNOWN
    facts, _, missing = to_rule_facts(store, "p1", DAY)
    assert "designation" not in facts and "legal" not in facts
    assert {"designation.query_complete", "legal.is_farmland"} <= set(missing)


def test_claim_does_not_override_an_official_unknown() -> None:
    store = FactStore()
    store.add(fact("land.slope", None, status=FactStatus.UNKNOWN, note="layer error"))
    store.add(claim("land.slope", 10))
    resolution = store.current("land.slope", "p1", DAY)
    assert not resolution.known


# ------------------------------------------------------------------ NOT_APPLICABLE basis


def test_not_applicable_needs_evidence_on_the_unmet_path() -> None:
    catalog = catalog_with(("law-a", "v1"))
    item = candidate("law-a", "height", required_facts=["land.area"])
    store = FactStore()
    store.add(fact("land.area", 500))  # evidenced, but not the deciding path
    store.add(claim("land.flag", False))
    finding = assess(item, store, catalog, DAY, conditions={"land.flag": True})
    assert finding.status is Applicability.UNRESOLVED
    assert finding.reasons == ["근거 없는 사실로 비해당 판단 불가: land.flag"]

    backed = FactStore()
    backed.add(fact("land.area", 500))
    backed.add(fact("land.flag", False))
    decided = assess(item, backed, catalog, DAY, conditions={"land.flag": True})
    assert decided.status is Applicability.NOT_APPLICABLE


def test_claim_on_legal_status_cannot_rule_out_a_mandatory_candidate() -> None:
    catalog = catalog_with(("law-a", "v1"))
    store = FactStore()
    store.add(fact("designation.query_complete", True))
    store.add(claim("legal.is_farmland", False))
    item = candidate("law-a", "farmland_conversion", mandatory=True)
    conditions = {"designation.query_complete": True, "legal.is_farmland": True}
    finding = assess(item, store, catalog, DAY, conditions=conditions)
    assert finding.status is Applicability.UNRESOLVED


# ------------------------------------------------------------------ coverage


def _district_profile() -> ChecklistProfile:
    return ChecklistProfile(
        profile_id="t",
        version="1",
        law_families=["x", "district_plan"],
        items=[
            ChecklistItem(
                checklist_id="x.height",
                label="높이",
                law_family="x",
                topic="height",
                targets=[ProvisionTarget(work_id="law-a", article=1)],
                required_facts=["land.flag"],
            ),
            ChecklistItem(
                checklist_id="district_plan.decision",
                label="지구단위계획",
                law_family="district_plan",
                topic="district_plan",
                targets=[ProvisionTarget(work_id="law-dp", article=1)],
                trigger_designation="district_unit_plan",
                required_documents=["district_plan_decision"],
            ),
        ],
    )


def _district_catalog() -> LegalCatalog:
    catalog = catalog_with(("law-a", "v1"))
    catalog.add_version(version("law-dp", "v1"))
    catalog.add_provision(Provision(ref=ref("law-dp", "v1"), text="dp"))
    return catalog


def test_untriggered_mandatory_row_stays_open_while_query_is_incomplete() -> None:
    flow = workflow_with(
        catalog=_district_catalog(),
        profile=_district_profile(),
        rules=[rule()],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],
    )
    facts = [
        fact("land.flag", True),
        fact("designation.query_complete", None, status=FactStatus.UNKNOWN, note="point"),
        fact("building.height", 10, unit="m", subject="proj-1", fact_id="h"),
    ]
    output = flow.start_review(request(facts=facts))
    rows = {row["checklist_id"]: row for row in output["coverage_items"]}
    assert rows["district_plan.decision"]["state"] == "unresolved"
    assert any(item["blocking"] for item in output["unresolved_items"])
    assert output["summary"]["legacy_status"] != "permitted"


def test_untriggered_row_is_skipped_only_on_an_evidenced_negative() -> None:
    catalog, profile = _district_catalog(), _district_profile()

    def rows(store: FactStore) -> set[str]:
        return {row.checklist_id for row in plan(catalog, store, [], profile=profile).coverage}

    complete = FactStore()
    complete.add(fact("designation.query_complete", True))
    assert rows(complete) == {"x.height"}

    absent = FactStore()
    absent.add(fact("designation.district_unit_plan", False))
    assert rows(absent) == {"x.height"}

    claimed = FactStore()
    claimed.add(claim("designation.query_complete", True))
    assert "district_plan.decision" in rows(claimed)


def test_claimed_documents_do_not_close_missing_document_gaps() -> None:
    store = FactStore()
    store.add(fact("designation.district_unit_plan", True))
    documents = [
        document
        for item in default_profile().items
        if item.checklist_id == "district_plan.decision"
        for document in item.required_documents
    ]
    assert documents
    for document in documents:
        item = claim(f"document.{document}", True)
        assert client_fact_problems([item])
        store.add(item)
    result = plan(LegalCatalog(), store, [])
    assert "missing_document" in {item.kind for item in result.unresolved}

    collected = FactStore()
    collected.add(fact("designation.district_unit_plan", True))
    for document in documents:
        collected.add(fact(f"document.{document}", True))
    assert "missing_document" not in {
        item.kind for item in plan(LegalCatalog(), collected, []).unresolved
    }


# ------------------------------------------------------------------ parent paths


def _outcome(output: dict[str, Any]) -> tuple[str, str]:
    return output["rule_evaluations"][0]["outcome"], output["summary"]["legacy_status"]


def test_parent_path_claim_cannot_set_an_exception_flag() -> None:
    flow = _slope_flow(exceptions=[Clause(fact_path="land.exempt", operator="==", value=True)])
    official = [fact("land.flag", True), fact("land.slope", 20)]
    assert _outcome(flow.start_review(request(facts=official)))[0] != "PASS"
    for revision, subject in (("r2", "proj-1"), ("r3", "p1")):
        parent = claim("land", {"exempt": True}, subject=subject)
        assert client_fact_problems([parent])  # refused at the boundary (REST 422)
        # Defence in depth: added anyway, the mapping never reaches the rule input.
        output = flow.start_review(
            request(facts=[*official, parent], the_proposal=proposal(revision=revision))
        )
        assert _outcome(output) != ("PASS", "permitted")
        assert output["rule_evaluations"][0]["outcome"] != "PASS"


def test_claim_cannot_set_the_engine_exception_override() -> None:
    """rase.exempted is the compiled exception override; only the engine may set it."""

    flow = _slope_flow(exceptions=[Clause(fact_path="land.exempt", operator="==", value=True)])
    official = [fact("land.flag", True), fact("land.slope", 20), fact("land.exempt", False)]
    assert _outcome(flow.start_review(request(facts=official))) == ("FAIL", "not_permitted")
    for revision, subject in (("r2", "proj-1"), ("r3", "p1")):
        override = claim("rase.exempted", True, subject=subject)
        assert client_fact_problems([override])  # refused at the boundary (REST 422)
        # Defence in depth: added anyway, the reserved root never reaches the rule input.
        output = flow.start_review(
            request(facts=[*official, override], the_proposal=proposal(revision=revision))
        )
        assert _outcome(output)[0] != "PASS"
        assert output["summary"]["legacy_status"] != "permitted"


def test_parent_path_claim_cannot_state_legal_status() -> None:
    flow = workflow_with(
        rules=[rule(requirement=Clause(fact_path="legal.is_farmland", operator="==", value=False))],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],
    )
    official = [fact("land.flag", True), fact("legal.is_farmland", None, status=FactStatus.UNKNOWN)]
    assert _outcome(flow.start_review(request(facts=official)))[0] == "REVIEW"
    parent = claim("legal", {"is_farmland": False})
    assert client_fact_problems([parent])
    output = flow.start_review(
        request(facts=[*official, parent], the_proposal=proposal(revision="r2"))
    )
    assert _outcome(output)[0] == "REVIEW"
    assert output["summary"]["legacy_status"] != "permitted"


def test_parent_path_claim_cannot_bypass_a_fact_binding_or_set_fact_units() -> None:
    binding = FactBinding(path="building.height", allowed_methods=["official_record"])
    flow = workflow_with(
        rules=[rule(fact_bindings=[binding])],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],
    )
    building = claim("building", {"height": 10}, subject="proj-1")
    units = claim("fact_units", {"building.height": "m"}, subject="proj-1")
    context = claim("context", {"jurisdiction": "99999"}, subject="proj-1")
    for item in (building, units, context):
        assert client_fact_problems([item])
    output = flow.start_review(request(facts=[fact("land.flag", True), building, units]))
    assert output["rule_evaluations"][0]["outcome"] == "REVIEW"
    assert output["summary"]["legacy_status"] != "permitted"


def test_client_paths_must_be_canonical_leaves() -> None:
    for path in ("Legal.is_farmland", " legal.is_farmland", "land.Jimok", "legal..x", "x."):
        assert client_fact_problems([claim(path, False, fact_id=f"c:{path!r}")]), path
    for path in ("legal", "designation", "document", "land", "LAND", "fact_units.x", "context"):
        assert client_fact_problems([claim(path, 1, fact_id=f"c:{path}")]), path
    assert client_fact_problems([claim("x.height", {"value": 10})])
    assert client_fact_problems([claim("land.slope", 10)]) == []


def test_to_rule_facts_drops_overlapping_reserved_and_claimed_mapping_paths() -> None:
    store = FactStore()
    store.add(fact("designation.query_complete", None, status=FactStatus.UNKNOWN))
    store.add(claim("designation", {"query_complete": True}))
    store.add(fact("land.slope", 20))
    store.add(fact("land", {"slope": 5}, fact_id="land-parent"))  # collected, but overlapping
    store.add(fact("fact_units", {"land.slope": "deg"}, fact_id="units"))
    store.add(claim("x.size", {"value": 10}))
    facts, used, missing = to_rule_facts(store, "p1", DAY)
    assert facts == {}
    assert used == []
    assert {"designation", "land", "land.slope", "fact_units", "x.size"} <= set(missing)


def test_collected_facts_with_other_casing_still_reach_rule_input() -> None:
    store = FactStore()
    store.add(fact("land.Zone_Code", "UQA", fact_id="zone"))
    facts, used, _missing = to_rule_facts(store, "p1", DAY)
    assert facts["land"]["Zone_Code"] == "UQA" and used == ["zone"]


# ------------------------------------------------------------------ observation scope


def test_partial_scope_negative_keeps_the_mandatory_row() -> None:
    catalog, profile = _district_catalog(), _district_profile()

    def rows(store: FactStore) -> set[str]:
        return {row.checklist_id for row in plan(catalog, store, [], profile=profile).coverage}

    for scope in ("partial", "sample"):
        absent = FactStore()
        absent.add(fact("designation.district_unit_plan", False, observation_scope=scope))
        assert "district_plan.decision" in rows(absent), scope
        complete = FactStore()
        complete.add(fact("designation.query_complete", True, observation_scope=scope))
        assert "district_plan.decision" in rows(complete), scope

    flow = workflow_with(
        catalog=catalog,
        profile=profile,
        rules=[rule()],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],
    )
    output = flow.start_review(
        request(
            facts=[
                fact("land.flag", True),
                fact("designation.district_unit_plan", False, observation_scope="partial"),
                fact("building.height", 10, unit="m", subject="proj-1", fact_id="h"),
            ]
        )
    )
    assert "district_plan.decision" in {row["checklist_id"] for row in output["coverage_items"]}
    assert any(item["blocking"] for item in output["unresolved_items"])
    assert output["summary"]["legacy_status"] != "permitted"


# ------------------------------------------------------------------ isolated defence layers


def test_fact_store_never_resolves_a_collection_only_path_from_a_claim() -> None:
    # Only the store-side filter is under test: no collected row exists for these paths.
    store = FactStore()
    for path in ("legal.is_farmland", "designation.query_complete", "land.jimok"):
        store.add(claim(path, False))
        assert store.current(path, "p1", DAY).status is FactStatus.UNKNOWN, path
    facts, used, missing = to_rule_facts(store, "p1", DAY)
    assert facts == {} and used == []
    assert {"legal.is_farmland", "designation.query_complete", "land.jimok"} <= set(missing)


def test_unevidenced_official_document_does_not_close_a_missing_document_gap() -> None:
    # Not a claim, so the store filter passes it; only the ``evidenced`` check keeps the gap open.
    catalog, profile = _district_catalog(), _district_profile()
    store = FactStore()
    store.add(fact("designation.district_unit_plan", True))
    store.add(
        fact(
            "document.district_plan_decision",
            True,
            status=FactStatus.ASSERTED,
            evidence_ids=[],
            fact_id="doc",
        )
    )
    assert store.current("document.district_plan_decision", "p1", DAY).known
    result = plan(catalog, store, [], profile=profile)
    assert "missing_document" in {item.kind for item in result.unresolved}

    backed = FactStore()
    backed.add(fact("designation.district_unit_plan", True))
    backed.add(fact("document.district_plan_decision", True, fact_id="doc"))
    result = plan(catalog, backed, [], profile=profile)
    assert "missing_document" not in {item.kind for item in result.unresolved}
