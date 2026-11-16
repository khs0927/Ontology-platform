"""Regression tests for review findings on claims versus collected facts.

Policy under test (framework plan sections 7 and 16): a caller's claim never overrides, fills or
resolves a collected fact; collection-only paths are resolved only by evidenced server-side facts;
rule inputs are bound per subject; NOT_APPLICABLE and skipped coverage need an evidenced basis on
the deciding path. All values are synthetic fixtures.
"""

from __future__ import annotations

from typing import Any

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
