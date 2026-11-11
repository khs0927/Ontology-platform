"""Scenarios S01-S32 of docs/regulation/regulation-validation-roadmap-2026-10-11.md.

All laws, parcels and values here are synthetic processing fixtures. They exercise the workflow
contract; they are not legal answers for any real parcel.
"""

# ruff: noqa: E402

from __future__ import annotations

import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

# The minimal ".[test]" install has no greenlet. Importing the workflow pulls
# archontos.rules, which then raises ImportError rather than ModuleNotFoundError.
pytest.importorskip("sion_regulation.review.workflow", exc_type=ImportError)

from sion_regulation.review import ReviewRequest, ReviewWorkflow
from sion_regulation.review.aggregate import legacy_decision, summarize
from sion_regulation.review.applicability import ReviewedRelation, assess, detect_conflicts
from sion_regulation.review.candidates import (
    ChecklistItem,
    ChecklistProfile,
    DesignationLink,
    ProvisionTarget,
    default_profile,
    generate_candidates,
)
from sion_regulation.review.citations import drop_unverified, verify_citations
from sion_regulation.review.facts import FactStore, facts_from_land_record, to_rule_facts
from sion_regulation.review.impact import ImpactGraph, classify_change
from sion_regulation.review.legal import (
    LegalCatalog,
    expand_references,
    parse_article_label,
    verify_returned_provision,
)
from sion_regulation.review.model import (
    Applicability,
    ApplicabilityFinding,
    CandidateProvision,
    CandidateSource,
    Citation,
    CollectionResult,
    CollectionStatus,
    CoverageItem,
    ErrorKind,
    Evidence,
    ExecutionStatus,
    Fact,
    FactStatus,
    InterpretationReview,
    Interval,
    LegalEventDates,
    LegalVersion,
    Outcome,
    ParcelPart,
    Proposal,
    Provision,
    ProvisionRef,
    RuleEvaluationRecord,
    Site,
    SourceRef,
    UnresolvedItem,
)
from sion_regulation.review.rase import (
    SUPPORT_TABLE,
    Clause,
    RaseRule,
    RuleBasis,
    RuleReview,
    RuleTest,
    Unsupported,
    compile_rase,
    evaluate_candidate,
    run_rule_tests,
)
from sion_regulation.review.retrieval import RetrievalScope, retrieve
from sion_regulation.review.runs import (
    IdempotencyConflict,
    InMemoryRunStore,
    ReviewOutbox,
    RunDAG,
    RunEngine,
    RunNode,
    missing_ledger,
)
from sion_regulation.review.sources import (
    FixtureProvider,
    ProviderProfile,
    ProviderRegistry,
    RetryPolicy,
    classify_http,
    fetch_with_retry,
    resolve_site,
)
from sion_regulation.review.workflow import client_fact_problems

DAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 9, tzinfo=UTC)
HASH = "a" * 64
OTHER_HASH = "b" * 64
JURISDICTION = "11110"


def source() -> SourceRef:
    return SourceRef(provider="fixture", contract="fixture/1", retrieved_at=NOW)


def evidence(evidence_id: str, *, excerpt: str = "", **extra: Any) -> Evidence:
    return Evidence(
        evidence_id=evidence_id, source=source(), snapshot_hash=HASH, excerpt=excerpt, **extra
    )


def version(
    work: str, vid: str, start: date | None = date(2020, 1, 1), **extra: Any
) -> LegalVersion:
    end = extra.pop("end", None)
    return LegalVersion(
        work_id=work,
        version_id=vid,
        title=extra.pop("title", work),
        effective=Interval(valid_from=start, valid_to=end),
        authority=extra.pop("authority", "act"),
        snapshot_hash=extra.pop("snapshot_hash", HASH),
        **extra,
    )


def ref(work: str = "law-a", vid: str = "v1", article: int = 1, **extra: Any) -> ProvisionRef:
    return ProvisionRef(work_id=work, version_id=vid, article=article, **extra)


def fact(path: str, value: Any, subject: str = "p1", **extra: Any) -> Fact:
    status = extra.pop("status", FactStatus.OBSERVED)
    evidence_ids = extra.pop("evidence_ids", ["ev-1"])
    return Fact(
        fact_id=extra.pop("fact_id", f"{subject}:{path}:{value}"),
        path=path,
        subject=subject,
        value=value,
        status=status,
        method=extra.pop("method", "official_record"),
        validity=extra.pop("validity", Interval(valid_from=date(2026, 1, 1))),
        recorded_at=extra.pop("recorded_at", NOW),
        evidence_ids=evidence_ids,
        **extra,
    )


def site(*parts: str, jurisdiction: str | None = JURISDICTION) -> Site:
    names = parts or ("p1",)
    return Site(
        address="합성 주소 1",
        pnus=["1111010100100010000"],
        parts=[ParcelPart(part_id=name, pnu="1111010100100010000") for name in names],
        jurisdiction_code=jurisdiction,
        resolved=True,
    )


def proposal(**extra: Any) -> Proposal:
    return Proposal(
        project_id=extra.pop("project_id", "proj-1"),
        revision=extra.pop("revision", "r1"),
        actions=extra.pop("actions", ["new_construction"]),
        uses=extra.pop("uses", ["warehouse"]),
        **extra,
    )


def catalog_with(*works: tuple[str, str], article: int = 1) -> LegalCatalog:
    catalog = LegalCatalog()
    for work, vid in works:
        catalog.add_version(version(work, vid))
        catalog.add_provision(Provision(ref=ref(work, vid, article), text=f"{work} 본문"))
    return catalog


def plan(
    catalog: LegalCatalog,
    facts: FactStore,
    links: list[DesignationLink],
    *,
    the_site: Site | None = None,
    the_proposal: Proposal | None = None,
    profile: ChecklistProfile | None = None,
    **extra: Any,
) -> Any:
    active = profile or default_profile()
    return generate_candidates(
        active.scope(),
        the_site or site(),
        the_proposal or proposal(),
        facts,
        links,
        catalog,
        day=DAY,
        profile=active,
        **extra,
    )


def link(designation: str, work: str, topic: str, **extra: Any) -> DesignationLink:
    return DesignationLink(
        designation=designation,
        target=ProvisionTarget(work_id=work, article=extra.pop("article", 1)),
        topic=topic,
        source_version="fixture-2026",
        **extra,
    )


def kinds(result: Any) -> set[str]:
    return {item.kind for item in result.unresolved}


def candidate(work: str, topic: str, subject: str = "p1", **extra: Any) -> CandidateProvision:
    return CandidateProvision(
        candidate_id=extra.pop("candidate_id", f"c-{work}-{topic}"),
        ref=ref(work),
        topic=topic,
        subject=subject,
        sources=[CandidateSource.REVIEWED_CATALOG],
        reasons=["fixture"],
        **extra,
    )


def rule(**extra: Any) -> RaseRule:
    approved = extra.pop("approved", True)
    review = RuleReview(
        author_role="rule_author",
        reviewer_role="legal_reviewer" if approved else None,
        status=InterpretationReview.APPROVED if approved else InterpretationReview.UNREVIEWED,
        reviewed_on=DAY if approved else None,
    )
    return RaseRule(
        rule_version_id=extra.pop("rule_version_id", "rule-1"),
        basis=extra.pop("basis", RuleBasis(ref=ref(), snapshot_hash=HASH)),
        topic="height",
        jurisdiction_code=JURISDICTION,
        requirement=extra.pop(
            "requirement", Clause(fact_path="building.height", operator="<=", value=12, unit="m")
        ),
        review=review,
        **extra,
    )


def rule_facts(height: float | None = 10) -> dict[str, Any]:
    facts: dict[str, Any] = {"context": {"jurisdiction": JURISDICTION}}
    if height is not None:
        facts["building"] = {"height": height}
        facts["fact_units"] = {"building.height": "m"}
    return facts


# ------------------------------------------------------------------ S01-S03 site and geometry


def test_s01_multiple_address_matches_are_never_auto_picked() -> None:
    resolved = resolve_site([{"pnu": "1" * 19}, {"pnu": "2" * 19}], address="합성 주소")
    assert not resolved.resolved and not resolved.pnus and len(resolved.candidates) == 2
    result = plan(LegalCatalog(), FactStore(), [], the_site=resolved)
    assert "site_ambiguous" in kinds(result)
    assert any(task.role == "user" for task in result.tasks)


def test_s02_partial_overlap_keeps_each_part() -> None:
    resolved = resolve_site(
        [{"pnu": "1" * 19, "parts": [{"part_id": "north"}, {"part_id": "south"}]}]
    )
    assert [part.part_id for part in resolved.parts] == ["north", "south"]

    catalog = catalog_with(("law-green", "v1"), ("law-res", "v1"))
    store = FactStore()
    store.add(fact("designation.green", True, "north"))
    store.add(fact("designation.residential", True, "south"))
    links = [link("green", "law-green", "use"), link("residential", "law-res", "use")]
    result = plan(catalog, store, links, the_site=site("north", "south"))
    by_subject = {c.subject: c.ref.work_id for c in result.candidates if c.topic == "use"}
    assert by_subject == {"north": "law-green", "south": "law-res"}


@pytest.mark.parametrize(
    ("precision", "errors"),
    [("point", []), ("polygon", [{"layer": "LT_C_UQ111", "error_code": "TIMEOUT"}])],
)
def test_s03_incomplete_spatial_query_is_not_a_negative(precision: str, errors: list[Any]) -> None:
    record = {
        "query": "합성",
        "parcel": {"pnu": "1" * 19, "jimok": "전", "is_mountain_register": False},
        "zoning": {"use_zone": [], "use_district": [], "use_area": []},
        "district_plan": [],
        "urban_facility": [],
        "layer_errors": errors,
        "source": {"precision": precision},
    }
    facts, _ = facts_from_land_record(record, NOW, subject="p1")
    store = FactStore()
    for item in facts:
        store.add(item)
    assert store.current("designation.query_complete", "p1", DAY).status is FactStatus.UNKNOWN
    _, _, missing = to_rule_facts(store, "p1", DAY)
    assert "designation.query_complete" in missing


# ------------------------------------------------------------------ S04-S10 discovery


def test_s04_agricultural_candidate_needs_legal_farmland_fact() -> None:
    catalog = catalog_with(("law-farm", "v1"))
    store = FactStore()
    store.add(fact("designation.agri_promotion", True))
    store.add(fact("land.jimok", "전"))
    links = [
        link(
            "agri_promotion",
            "law-farm",
            "farmland_conversion",
            required_facts=["legal.is_farmland", "proposal.actions"],
        )
    ]
    result = plan(catalog, store, links)
    target = next(c for c in result.candidates if c.topic == "farmland_conversion")
    assert target.sources[0] is CandidateSource.OFFICIAL_DESIGNATION_LINK
    finding = assess(target, store, catalog, DAY, conditions={"legal.is_farmland": True})
    assert finding.status is Applicability.UNRESOLVED
    assert "legal.is_farmland" in finding.missing_facts


def test_s05_register_category_does_not_decide_legal_mountain_land() -> None:
    record = {
        "query": "합성",
        "parcel": {"pnu": "1" * 19, "jimok": "임야", "is_mountain_register": True},
        "zoning": {},
        "layer_errors": [],
        "source": {"precision": "polygon"},
    }
    facts, _ = facts_from_land_record(record, NOW, subject="p1")
    store = FactStore()
    for item in facts:
        store.add(item)
    assert store.current("land.jimok", "p1", DAY).value == "임야"
    assert store.current("legal.is_mountain_land", "p1", DAY).status is FactStatus.UNKNOWN


def test_s06_overlapping_laws_are_reviewed_in_parallel() -> None:
    catalog = catalog_with(("law-nlupa", "v1"), ("law-farm", "v1"), ("law-mount", "v1"))
    store = FactStore()
    store.add(fact("designation.agri_promotion", True))
    store.add(fact("designation.conservation_mountain", True))
    links = [
        link("agri_promotion", "law-farm", "farmland_conversion"),
        link("agri_promotion", "law-nlupa", "use_permission"),
        link("conservation_mountain", "law-mount", "mountain_conversion"),
    ]
    result = plan(catalog, store, links)
    works = {c.ref.work_id for c in result.candidates}
    assert works == {"law-nlupa", "law-farm", "law-mount"}
    findings = [assess(c, store, catalog, DAY) for c in result.candidates]
    assert all(f.status is Applicability.UNRESOLVED for f in findings)
    assert detect_conflicts(result.candidates, findings) == []


def test_s07_district_plan_without_documents_stays_open() -> None:
    catalog = LegalCatalog()
    store = FactStore()
    store.add(fact("designation.district_unit_plan", True))
    result = plan(catalog, store, [])
    assert "missing_document" in kinds(result)
    row = next(c for c in result.coverage if c.checklist_id == "district_plan.decision")
    assert row.state == "unresolved"
    summary = summarize(result.coverage, [], [], [], result.unresolved)
    assert summary.legacy_status != "permitted"


def test_s08_ordinance_of_another_jurisdiction_is_excluded() -> None:
    catalog = LegalCatalog()
    catalog.add_version(version("ord-a", "v1", authority="ordinance", jurisdiction_code="11110"))
    catalog.add_version(version("ord-b", "v1", authority="ordinance", jurisdiction_code="26110"))
    for work in ("ord-a", "ord-b"):
        catalog.add_provision(Provision(ref=ref(work), text="같은 이름의 조례"))
    item = ChecklistItem(
        checklist_id="ordinance.local",
        label="조례",
        law_family="ordinance",
        topic="local_ordinance",
        targets=[
            ProvisionTarget(work_id="ord-a", article=1),
            ProvisionTarget(work_id="ord-b", article=1),
        ],
        jurisdictional=True,
    )
    profile = ChecklistProfile(
        profile_id="t", version="1", law_families=["ordinance"], items=[item]
    )
    result = plan(catalog, FactStore(), [], profile=profile)
    assert {c.ref.work_id for c in result.candidates} == {"ord-a"}

    unknown = plan(catalog, FactStore(), [], profile=profile, the_site=site(jurisdiction=None))
    assert "missing_fact" in kinds(unknown)


def test_s09_other_law_overlay_creates_follow_up_work() -> None:
    store = FactStore()
    store.add(fact("designation.river_area", True))
    result = plan(LegalCatalog(), store, [])
    assert "unsupported_source" in kinds(result)
    assert any("river_area" in task.target for task in result.tasks)


def test_s10_shared_access_expands_scope() -> None:
    store = FactStore()
    store.add(fact("site.shared_access", True))
    assert "scope_expansion" in kinds(plan(LegalCatalog(), store, []))
    two = site()
    two.pnus = ["1" * 19, "2" * 19]
    assert "scope_expansion" in kinds(plan(LegalCatalog(), FactStore(), [], the_site=two))


# ------------------------------------------------------------------ S11-S16 time and identity


def test_s11_past_permit_uses_the_version_in_force_then() -> None:
    catalog = LegalCatalog()
    catalog.add_version(version("law-a", "old", date(2010, 1, 1), end=date(2024, 1, 1)))
    catalog.add_version(version("law-a", "new", date(2024, 1, 1)))
    dates = LegalEventDates(review_date=DAY, permit_date=date(2020, 5, 1))
    resolved = catalog.version_at("law-a", dates.governing_date())
    assert resolved is not None and resolved.version_id == "old"
    assert catalog.version_at("law-a", DAY).version_id == "new"  # type: ignore[union-attr]


def test_s11_ambiguous_version_is_unresolved() -> None:
    catalog = LegalCatalog()
    catalog.add_version(version("law-a", "x", date(2020, 1, 1)))
    catalog.add_version(version("law-a", "y", date(2021, 1, 1)))
    assert catalog.version_at("law-a", DAY) is None
    assert "overlapping" in str(catalog.resolve_version("law-a", DAY).reason)


def test_s12_current_map_does_not_answer_for_the_past() -> None:
    store = FactStore()
    store.add(fact("designation.green", True, validity=Interval(valid_from=date(2026, 1, 1))))
    past = date(2015, 1, 1)
    assert store.current("designation.green", "p1", past).status is FactStatus.UNKNOWN
    undated = FactStore()
    undated.add(fact("designation.green", True, validity=Interval()))
    resolution = undated.current("designation.green", "p1", past)
    assert resolution.status is FactStatus.UNKNOWN and resolution.facts
    assert to_rule_facts(undated, "p1", past)[2] == ["designation.green"]


def test_s13_unknown_exception_stays_review() -> None:
    catalog = catalog_with(("law-a", "v1"))
    exception = ref("law-a", "v1", 2)
    item = candidate("law-a", "height", exceptions_to_check=[exception])
    store = FactStore()
    store.add(fact("land.flag", True))
    finding = assess(
        item,
        store,
        catalog,
        DAY,
        conditions={"land.flag": True},
        exception_facts={exception.key: "land.exception"},
    )
    assert finding.status is Applicability.UNRESOLVED
    assert finding.unresolved_exceptions == [exception.key]

    excepted = rule(exceptions=[Clause(fact_path="land.exception", operator="==", value=True)])
    record = evaluate_candidate(excepted, rule_facts(99), candidate_id="c")
    assert record.outcome is Outcome.REVIEW
    summary = summarize(
        [CoverageItem(checklist_id="x", label="x", subject="p1", state="satisfied")],
        [finding],
        [record],
        [],
        [],
    )
    assert summary.has_unresolved and summary.legacy_status == "insufficient_data"


def test_s14_circular_references_terminate_and_keep_required_text() -> None:
    catalog = LegalCatalog()
    catalog.add_version(version("law-a", "v1"))
    one, two, annex = (
        ref(article=1),
        ref(article=2),
        ProvisionRef(work_id="law-a", version_id="v1", kind="annex", annex_no="1"),
    )
    catalog.add_provision(Provision(ref=one, text="1", references=[two]))
    catalog.add_provision(Provision(ref=two, text="2", references=[one, annex]))
    catalog.add_provision(Provision(ref=annex, text="별표"))
    expansion = expand_references(catalog, [one], max_depth=5)
    assert expansion.visited == [one.key, two.key, annex.key]
    assert not expansion.depth_capped

    capped = expand_references(catalog, [one], max_depth=1)
    assert capped.depth_capped and capped.capped_refs == [annex]


def test_s15_same_title_different_work_is_not_merged() -> None:
    catalog = LegalCatalog()
    catalog.add_version(version("law-1", "v1", title="동명 법률"))
    catalog.add_version(version("law-2", "v1", title="동명 법률"))
    assert ref("law-1").key != ref("law-2").key
    assert len(catalog.lineage("law-1")) == len(catalog.lineage("law-2")) == 1
    renamed = version("law-1", "v2", date(2025, 1, 1), title="새 이름")
    catalog.add_version(renamed)
    assert [v.version_id for v in catalog.lineage("law-1")] == ["v1", "v2"]
    assert parse_article_label("제12조의2제3항제1호의2가목") == {
        "kind": "article",
        "article": 12,
        "branch": 2,
        "paragraph": 3,
        "item": 1,
        "item_branch": 2,
        "sub_item": "가",
    }
    assert parse_article_label("별표 2의3") == {"kind": "annex", "annex_no": "2의3"}
    with pytest.raises(ValueError, match="unrecognised"):
        parse_article_label("제12조 어딘가")


def test_s16_returned_article_mismatch_is_rejected() -> None:
    requested = ref(article=12, branch=2)
    returned = Provision(ref=ref(article=12), text="다른 조문")
    assert "branch" in str(verify_returned_provision(requested, returned))
    assert verify_returned_provision(requested, Provision(ref=requested, text="x")) is None


# ------------------------------------------------------------------ S17-S22 conflicts and facts


def test_s17_conflicting_sources_are_preserved_without_a_winner() -> None:
    store = FactStore()
    store.add(fact("land.area", 100, fact_id="a", evidence_ids=["ev-a"]))
    store.add(fact("land.area", 120, fact_id="b", evidence_ids=["ev-b"]))
    resolution = store.current("land.area", "p1", DAY)
    assert resolution.status is FactStatus.DISPUTED and resolution.fact_ids == ["a", "b"]
    assert "land.area" in to_rule_facts(store, "p1", DAY)[2]

    first, second = candidate("law-a", "height"), candidate("law-b", "height")
    positions = {first.candidate_id: "12m", second.candidate_id: "9m"}
    conflicts = detect_conflicts([first, second], [], positions=positions)
    assert len(conflicts) == 1 and conflicts[0].kind == "unresolved"
    assert sorted(conflicts[0].candidate_ids) == sorted([first.candidate_id, second.candidate_id])

    relation = ReviewedRelation(
        candidate_ids=[first.candidate_id, second.candidate_id],
        kind="exception",
        evidence_ids=["ev-a"],
        review=InterpretationReview.APPROVED,
    )
    reviewed = detect_conflicts([first, second], [], positions=positions, reviewed=[relation])
    assert reviewed[0].kind == "exception" and reviewed[0].basis_evidence_ids == ["ev-a"]
    unapproved = relation.model_copy(update={"review": InterpretationReview.UNREVIEWED})
    still = detect_conflicts([first, second], [], positions=positions, reviewed=[unapproved])
    assert still[0].kind == "unresolved"


def test_s17_corroborated_only_with_independent_evidence() -> None:
    store = FactStore()
    store.add(fact("land.area", 100, fact_id="a", evidence_ids=["ev-a"]))
    store.add(fact("land.area", 100, fact_id="b", evidence_ids=["ev-b"]))
    assert store.current("land.area", "p1", DAY).status is FactStatus.CORROBORATED


def test_s18_different_topics_are_parallel_not_conflicts() -> None:
    first, second = candidate("law-a", "height"), candidate("law-b", "coverage")
    positions = {first.candidate_id: "12m", second.candidate_id: "60%"}
    assert detect_conflicts([first, second], [], positions=positions) == []
    other_subject = candidate("law-b", "height", "p2", candidate_id="c-other")
    positions[other_subject.candidate_id] = "9m"
    assert detect_conflicts([first, other_subject], [], positions=positions) == []


def test_s19_failures_are_classified_and_bounded() -> None:
    assert classify_http(200) is None
    assert classify_http(429) is ErrorKind.RATE_LIMITED
    assert classify_http(403) is ErrorKind.AUTH
    assert classify_http(503) is ErrorKind.TRANSIENT
    assert classify_http(422) is ErrorKind.SCHEMA

    policy = RetryPolicy(max_attempts=3, base_delay_seconds=1)
    assert policy.next_delay(ErrorKind.AUTH, 1) is None
    assert policy.next_delay(ErrorKind.SCHEMA, 1) is None
    assert policy.next_delay(ErrorKind.RATE_LIMITED, 1, 30) == 30
    assert policy.next_delay(ErrorKind.TRANSIENT, 2) == 2
    assert policy.next_delay(ErrorKind.TRANSIENT, 3) is None

    responses = {"k": {"status": "failed", "error_kind": "transient", "error": "503"}}
    provider = FixtureProvider("law", "c/1", frozenset({"law"}), responses)
    waits: list[float] = []
    result, attempts = fetch_with_retry(provider, {"key": "k"}, policy, waits.append)
    assert result.status is CollectionStatus.FAILED and attempts == 3 and waits == [1, 2]

    auth = FixtureProvider(
        "a", "c/1", frozenset({"law"}), {"k": {"status": "failed", "error_kind": "auth"}}
    )
    assert fetch_with_retry(auth, {"key": "k"}, policy, waits.append)[1] == 1


def _result(node: RunNode, status: CollectionStatus, **extra: Any) -> CollectionResult:
    return CollectionResult(node_id=node.node_id, provider=node.provider, status=status, **extra)


def test_s19_partial_run_lists_failures_with_owners() -> None:
    store = InMemoryRunStore()

    def executor(node: RunNode) -> CollectionResult:
        if node.node_id == "denied":
            return _result(node, CollectionStatus.FAILED, error_kind=ErrorKind.AUTH, error="403")
        if node.node_id == "limited":
            return _result(
                node,
                CollectionStatus.FAILED,
                error_kind=ErrorKind.RATE_LIMITED,
                retry_after_seconds=30,
            )
        return _result(node, CollectionStatus.FOUND)

    engine = RunEngine(store, {"p": executor}, clock=lambda: NOW)
    dag = RunDAG(
        [
            RunNode(node_id="ok", provider="p"),
            RunNode(node_id="denied", provider="p"),
            RunNode(node_id="limited", provider="p"),
            RunNode(node_id="after", provider="p", deps=["denied"]),
        ]
    )
    record = engine.execute(engine.create("proj", "r1", {"a": 1}, dag).run_id)
    assert record.status is ExecutionStatus.PARTIAL
    assert record.nodes["limited"].next_retry_at is not None
    assert record.nodes["denied"].next_retry_at is None
    assert record.nodes["after"].missing == ["blocked by denied"]
    _, tasks = missing_ledger(record)
    assert {task.role for task in tasks} == {"ops_admin", "data_operator"}


def test_s20_truncated_result_is_never_complete() -> None:
    with pytest.raises(ValueError, match="truncated"):
        CollectionResult(node_id="n", provider="p", status=CollectionStatus.FOUND, next_page="2")
    result = CollectionResult(
        node_id="n", provider="p", status=CollectionStatus.TRUNCATED, next_page="2"
    )
    assert not result.complete

    def executor(node: RunNode) -> CollectionResult:
        return _result(node, CollectionStatus.FOUND, items=[{"a": 1}], result_limit=1)

    engine = RunEngine(InMemoryRunStore(), {"p": executor})
    dag = RunDAG([RunNode(node_id="layer", provider="p")])
    record = engine.execute(engine.create("proj", "r1", {}, dag).run_id)
    assert record.nodes["layer"].collection is CollectionStatus.TRUNCATED
    assert record.status is ExecutionStatus.PARTIAL
    items, _ = missing_ledger(record)
    assert [item.kind for item in items] == ["truncated"]


def test_s21_ocr_value_needs_source_check_before_approval() -> None:
    basis = RuleBasis(ref=ref(), snapshot_hash=HASH, source_kind="ocr")
    with pytest.raises(ValueError, match="verified source span"):
        rule(basis=basis)
    assert (
        evaluate_candidate(
            rule(basis=basis, approved=False), rule_facts(), candidate_id="c"
        ).outcome
        is Outcome.REVIEW
    )
    checked = basis.model_copy(update={"span_verified": True})
    assert rule(basis=checked).review.status is InterpretationReview.APPROVED


def test_s22_observed_floors_are_not_the_whole_building() -> None:
    store = FactStore()
    store.add(fact("building.floors", 3, method="design_observed", observation_scope="partial"))
    facts, used, missing = to_rule_facts(store, "p1", DAY)
    assert "building" not in facts and used == [] and missing == ["building.floors"]


# ------------------------------------------------------------------ S23-S25 citations and scope


def test_s23_invented_citations_are_removed() -> None:
    target = ref()
    provision = Provision(ref=target, text="높이는 12미터 이하로 한다.", evidence_id="ev-1")
    evidence_index = {"ev-1": evidence("ev-1", excerpt="12미터 이하")}
    provisions = {target.key: provision}
    claims = [
        Citation(claim="실제", evidence_ids=["ev-1"], provision_key=target.key),
        Citation(claim="없는 근거", evidence_ids=["ev-404"], provision_key=target.key),
        Citation(claim="없는 조문", evidence_ids=["ev-1"], provision_key="law|x"),
        Citation(claim="자기 보증", evidence_ids=["ev-404"], verified=True),
    ]
    checked = verify_citations(claims, evidence_index, provisions)
    assert [c.verified for c in checked] == [True, False, False, False]
    assert [c.claim for c in drop_unverified(checked)] == ["실제"]

    wrong = {"ev-1": evidence("ev-1", excerpt="9미터 이하")}
    assert "not found" in str(verify_citations(claims[:1], wrong, provisions)[0].failure)


def workflow_with(**extra: Any) -> ReviewWorkflow:
    catalog = extra.pop("catalog", None) or catalog_with(("law-a", "v1"))
    profile = ChecklistProfile(
        profile_id="t",
        version="1",
        law_families=["x"],
        items=[
            ChecklistItem(
                checklist_id="x.height",
                label="높이",
                law_family="x",
                topic="height",
                targets=[ProvisionTarget(work_id="law-a", article=1)],
                required_facts=["land.flag"],
            )
        ],
    )
    return ReviewWorkflow(catalog, profile=extra.pop("profile", profile), **extra)


def request(**extra: Any) -> ReviewRequest:
    return ReviewRequest(
        proposal=extra.pop("the_proposal", proposal()),
        site=extra.pop("the_site", site()),
        legal_event_dates=LegalEventDates(review_date=DAY),
        **extra,
    )


def test_s24_unreviewed_relation_is_explained_as_candidate_only() -> None:
    flow = workflow_with(conditions={"height": {"land.flag": True}})
    output = flow.start_review(request())
    explanation = flow.explain(output["run_id"], "왜 후보인가", project_id="proj-1")
    assert explanation["evaluation_basis"] == []
    assert [c["topic"] for c in explanation["candidates_only"]] == ["height"]


def test_s25_private_material_never_crosses_projects() -> None:
    private = evidence("ev-private", public=False, project_id="proj-1", excerpt="사유 본문")
    catalog = LegalCatalog()
    catalog.add_version(version("law-a", "v1"))
    target = ref()
    catalog.add_provision(Provision(ref=target, text="사유 본문", evidence_id="ev-private"))
    flow = workflow_with(catalog=catalog, evidence=[private])
    assert flow.get_basis("ev-private", project_id="proj-1")["provision"] is not None
    with pytest.raises(PermissionError):
        flow.get_basis("ev-private", project_id="proj-2")

    index = {"ev-private": private}
    other = RetrievalScope(project_id="proj-2", as_of=DAY)
    found = retrieve("제1조", other, catalog, index, search=lambda _: [target.key])
    assert found.provisions == [] and found.filtered_out == 1
    mine = RetrievalScope(project_id="proj-1", as_of=DAY)
    assert retrieve("제1조", mine, catalog, index).provisions

    claim = Citation(claim="x", evidence_ids=["ev-private"])
    assert not verify_citations([claim], index, {}, project_id="proj-2")[0].verified

    output = flow.start_review(request())
    with pytest.raises(PermissionError):
        flow.get_review(output["run_id"], project_id="proj-2")


def test_retrieval_keeps_required_provisions_past_the_search_limit() -> None:
    catalog = LegalCatalog()
    catalog.add_version(version("law-a", "v1"))
    refs = [ref(article=n) for n in range(1, 6)]
    for item in refs:
        catalog.add_provision(Provision(ref=item, text=str(item.article)))
    scope = RetrievalScope(project_id="p", as_of=DAY)
    found = retrieve(
        "q",
        scope,
        catalog,
        {},
        [refs[4]],
        search=lambda _: [r.key for r in refs[:4]],
        limit=2,
    )
    keys = [p.ref.key for p in found.provisions]
    assert refs[4].key in keys and len(keys) == 2


# ------------------------------------------------------------------ S26-S29 durability


def test_s26_same_run_retry_is_not_duplicated_and_key_conflict_is_refused() -> None:
    calls: list[str] = []

    def executor(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        return _result(node, CollectionStatus.FOUND)

    store = InMemoryRunStore()
    flow = workflow_with(store=store, executors={"p": executor})
    nodes = [RunNode(node_id="n", provider="p")]
    first = flow.start_review(request(requested_sources=nodes))
    again = flow.start_review(request(requested_sources=nodes))
    assert first == again and calls == ["n"]
    assert store.revisions(first["run_id"]) == [1]

    keyed = request(idempotency_key="k1")
    flow.start_review(keyed)
    other = request(idempotency_key="k1", the_proposal=proposal(actions=["use_change"]))
    with pytest.raises(IdempotencyConflict):
        flow.start_review(other)


class Crash(Exception):
    """Stands in for a process that dies: nothing in the engine catches it."""


def test_s27_restart_resumes_from_checkpoints() -> None:
    store = InMemoryRunStore()
    calls: list[str] = []

    def crashing(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        if node.node_id == "second":
            raise Crash
        return _result(node, CollectionStatus.FOUND)

    dag = RunDAG(
        [
            RunNode(node_id="first", provider="p"),
            RunNode(node_id="second", provider="p", deps=["first"]),
        ]
    )
    engine = RunEngine(store, {"p": crashing})
    run_id = engine.create("proj", "r1", {}, dag).run_id
    with pytest.raises(Crash):
        engine.execute(run_id)
    stored = store.load(run_id)
    assert stored.nodes["first"].status is ExecutionStatus.COMPLETED
    assert stored.nodes["second"].status is ExecutionStatus.RUNNING

    def healthy(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        return _result(node, CollectionStatus.FOUND)

    record = RunEngine(store, {"p": healthy}).resume(run_id)
    assert record.status is ExecutionStatus.COMPLETED and record.run_revision == 2
    assert calls == ["first", "second", "second"]
    assert record.nodes["first"].reused_from_revision == 1


def test_s27_save_receipt_is_read_back_and_outbox_is_idempotent() -> None:
    outbox = ReviewOutbox()
    flow = workflow_with(outbox=outbox)
    output = flow.start_review(request())
    receipt = flow.save_work(output["run_id"], project_id="proj-1", notes="n")
    assert flow.save_work(output["run_id"], project_id="proj-1", notes="n") == receipt
    assert len(outbox.pending()) == 1
    assert flow.verify_receipt(receipt)
    tampered = receipt.model_copy(update={"digest": "0" * 64})
    assert not flow.verify_receipt(tampered)

    delivered: list[str] = []
    with pytest.raises(Crash):

        def failing(_entry: Any) -> None:
            raise Crash

        outbox.drain(failing)
    assert outbox.drain(lambda entry: delivered.append(entry.key)) == 1
    assert outbox.drain(lambda entry: delivered.append(entry.key)) == 0
    assert len(delivered) == 1


def test_s28_source_change_keeps_old_report_and_opens_re_review() -> None:
    old = Provision(ref=ref(vid="v1"), text="높이 12미터", evidence_id="e1")
    new_text = Provision(ref=ref(vid="v2"), text="높이 9미터", evidence_id="e2")
    same_text = Provision(ref=ref(vid="v2"), text="높이 12미터", evidence_id="e2")
    change = classify_change(old, new_text)
    assert change.kind == "text"
    assert classify_change(old, same_text).kind == "hash_only"
    assert classify_change(old, old).kind == "none"
    moved = classify_change(
        old,
        old,
        old_version=version("law-a", "v1", date(2020, 1, 1)),
        new_version=version("law-a", "v1", date(2021, 1, 1)),
    )
    assert moved.kind == "effectivity"

    graph = ImpactGraph()
    graph.link_rule(old.ref.key, "rule-1")
    graph.link_evaluation("rule-1", "eval-1")
    graph.link_work("eval-1", "work-1", "rev-1")
    impacted = graph.impacted_works(change)
    assert [(i.work_id, i.work_revision, i.blocking) for i in impacted] == [
        ("work-1", "rev-1", True)
    ]
    assert not graph.impacted_works(classify_change(old, same_text))[0].blocking
    assert graph.impacted_works(classify_change(old, old)) == []

    flow = workflow_with()
    first = flow.start_review(request())
    snapshot = flow.get_review(first["run_id"], project_id="proj-1", revision=1)
    supplement = [fact("land.flag", True)]
    second = flow.resume_review(first["run_id"], project_id="proj-1", supplement=supplement)
    assert second["run_revision"] == 2
    assert flow.get_review(first["run_id"], project_id="proj-1", revision=1) == snapshot
    diff = flow.compare(
        first["run_id"], first["run_id"], project_id="proj-1", revision_a=1, revision_b=2
    )
    assert diff["changes"]["facts"]["added"] == [supplement[0].fact_id]


def test_s29_late_response_cannot_overwrite_a_cancelled_run() -> None:
    store = InMemoryRunStore()
    started, release = threading.Event(), threading.Event()

    def slow(node: RunNode) -> CollectionResult:
        started.set()
        assert release.wait(5)
        return _result(node, CollectionStatus.FOUND)

    engine = RunEngine(store, {"p": slow})
    dag = RunDAG(
        [RunNode(node_id="n", provider="p"), RunNode(node_id="m", provider="p", deps=["n"])]
    )
    run_id = engine.create("proj", "r1", {}, dag).run_id
    outcome: list[Any] = []
    worker = threading.Thread(target=lambda: outcome.append(engine.execute(run_id)))
    worker.start()
    assert started.wait(5)
    engine.cancel(run_id)
    release.set()
    worker.join(5)
    record = store.load(run_id)
    assert record.status is ExecutionStatus.CANCELLED
    assert record.nodes["n"].status is ExecutionStatus.CANCELLED and "n" not in record.results
    assert [item.node_id for item in record.late_results] == ["n"]
    with pytest.raises(ValueError, match="cancelled"):
        engine.resume(run_id)


# ------------------------------------------------------------------ S30-S32 independence


def test_s30_review_works_without_any_model() -> None:
    flow = workflow_with()
    output = flow.start_review(request())
    assert "# 규제 검토 브리핑" in flow.briefing(output["run_id"], project_id="proj-1")

    def broken(_question: str, _context: dict[str, Any]) -> str:
        raise RuntimeError("model down")

    explained = flow.explain(output["run_id"], "q", project_id="proj-1", explainer=broken)
    assert explained["generated"] is None and explained["generation_error"] == "RuntimeError"
    assert explained["candidates_only"]

    catalog = catalog_with(("law-a", "v1"))
    scope = RetrievalScope(project_id="p", as_of=DAY)

    def search(_question: str) -> list[str]:
        raise TimeoutError

    degraded = retrieve("제1조", scope, catalog, {}, search=search)
    assert degraded.provisions and degraded.degraded == "search unavailable: TimeoutError"


PACKAGE = Path(__file__).resolve().parents[1] / "src" / "sion_regulation" / "review"


def test_s31_regulation_path_has_no_jev_dependency() -> None:
    sources = "\n".join(p.read_text(encoding="utf-8") for p in PACKAGE.glob("*.py"))
    assert "jev" not in sources.lower()


def test_s32_review_package_stays_off_other_router_paths() -> None:
    sources = "\n".join(p.read_text(encoding="utf-8") for p in PACKAGE.glob("*.py"))
    for name in ("sion_cad", "god_cad", "sion_bim", "aec_intelligence", "httpx", "requests"):
        assert f"import {name}" not in sources and f"from {name}" not in sources


# ------------------------------------------------------------------ module contracts


def test_end_to_end_reviewed_rule_can_pass_only_with_everything_settled() -> None:
    catalog = catalog_with(("law-a", "v1"))
    target = ref()
    flow = workflow_with(
        catalog=catalog,
        rules=[rule()],
        conditions={"height": {"land.flag": True}},
        evidence=[evidence("ev-1")],
    )
    facts = [
        fact("land.flag", True),
        fact("building.height", 10, unit="m", subject="proj-1", fact_id="height"),
    ]
    output = flow.start_review(request(facts=facts))
    assert output["rule_evaluations"][0]["outcome"] == "PASS"
    assert output["summary"]["legacy_status"] == "permitted"
    assert output["summary"]["advisory"] is True
    assert output["legacy_decision"]["status"] == "insufficient_evidence"
    assert output["canonical"] is False and target.key

    failing = [facts[0], fact("building.height", 20, unit="m", subject="proj-1", fact_id="h2")]
    denied = flow.start_review(request(facts=failing, the_proposal=proposal(revision="r2")))
    assert denied["rule_evaluations"][0]["outcome"] == "FAIL"
    assert denied["summary"]["legacy_status"] == "not_permitted"


def test_applicable_provision_without_a_rule_blocks_permission() -> None:
    flow = workflow_with(conditions={"height": {"land.flag": True}}, evidence=[evidence("ev-1")])
    output = flow.start_review(request(facts=[]))
    assert output["summary"]["legacy_status"] == "insufficient_data"

    supplied = flow.resume_review(
        output["run_id"], project_id="proj-1", supplement=[fact("land.flag", True)]
    )
    assert supplied["rule_evaluations"][0]["outcome"] == "REVIEW"
    assert "RULE_REVIEW_REQUIRED" in supplied["summary"]["reason_codes"]
    assert supplied["summary"]["legacy_status"] == "insufficient_data"


def test_malformed_provider_fact_is_quarantined() -> None:
    def executor(node: RunNode) -> CollectionResult:
        bad = {"fact": {"fact_id": "x"}}
        good = {"fact": fact("land.flag", True).model_dump(mode="json")}
        return _result(node, CollectionStatus.FOUND, items=[bad, good])

    flow = workflow_with(executors={"p": executor})
    output = flow.start_review(request(requested_sources=[RunNode(node_id="n", provider="p")]))
    assert "quarantined" in {item["kind"] for item in output["unresolved_items"]}
    assert "land.flag" in {item["path"] for item in output["facts"]}


def test_client_fact_rules() -> None:
    forged = fact("land.flag", False)
    assert len(client_fact_problems([forged])) == 3
    honest = fact(
        "land.flag", False, status=FactStatus.ASSERTED, method="user_claim", evidence_ids=[]
    )
    assert client_fact_problems([honest]) == []


def test_shipped_profile_cannot_claim_coverage_yet() -> None:
    profile = default_profile()
    assert profile.reviewed is False
    result = plan(LegalCatalog(), FactStore(), [])
    assert result.coverage and all(item.state == "unresolved" for item in result.coverage)


def test_rase_support_table_and_compile() -> None:
    assert SUPPORT_TABLE["comparison"] == "supported"
    unsupported = compile_rase(rule(features=["comparison", "mutatis_mutandis"]))
    assert isinstance(unsupported, Unsupported)
    assert (
        evaluate_candidate(rule(features=["procedure"]), rule_facts(), candidate_id="c").outcome
        is Outcome.REVIEW
    )

    tested = rule(
        selection=[Clause(fact_path="land.flag", operator="==", value=True)],
        exceptions=[Clause(fact_path="land.exempt", operator="==", value=True)],
        tests=[
            RuleTest(
                name="pass",
                facts={**rule_facts(10), "land": {"flag": True, "exempt": False}},
                expected=Outcome.PASS,
            ),
            RuleTest(
                name="fail",
                facts={**rule_facts(30), "land": {"flag": True, "exempt": False}},
                expected=Outcome.FAIL,
            ),
            RuleTest(
                name="exempt",
                facts={**rule_facts(30), "land": {"flag": True, "exempt": True}},
                expected=Outcome.PASS,
            ),
            RuleTest(name="absent", facts=rule_facts(None), expected=Outcome.REVIEW),
            RuleTest(
                name="out of scope",
                facts={**rule_facts(10), "land": {"flag": False, "exempt": False}},
                expected=None,
            ),
            RuleTest(
                name="other jurisdiction",
                facts={
                    **rule_facts(10),
                    "context": {"jurisdiction": "26110"},
                    "land": {"flag": True, "exempt": False},
                },
                expected=None,
            ),
        ],
    )
    assert run_rule_tests(tested) == []


def test_stale_basis_hash_returns_to_review() -> None:
    record = evaluate_candidate(
        rule(), rule_facts(), candidate_id="c", current_snapshot_hash=OTHER_HASH
    )
    assert record.outcome is Outcome.REVIEW and not record.reviewed


def test_rule_author_cannot_approve_alone() -> None:
    with pytest.raises(ValueError, match="roles must differ"):
        RaseRule(
            rule_version_id="r",
            basis=RuleBasis(ref=ref(), snapshot_hash=HASH),
            topic="t",
            jurisdiction_code=JURISDICTION,
            requirement=Clause(fact_path="a", operator="==", value=1),
            review=RuleReview(
                author_role="x",
                reviewer_role="x",
                status=InterpretationReview.APPROVED,
                reviewed_on=DAY,
            ),
        )


def test_not_applicable_needs_evidence_and_known_facts() -> None:
    catalog = catalog_with(("law-a", "v1"))
    item = candidate("law-a", "height")
    store = FactStore()
    store.add(fact("land.flag", False))
    finding = assess(item, store, catalog, DAY, conditions={"land.flag": True})
    assert finding.status is Applicability.NOT_APPLICABLE and finding.evidence_ids

    claim = FactStore()
    claim.add(
        fact(
            "land.flag",
            False,
            status=FactStatus.ASSERTED,
            method="user_claim",
            evidence_ids=[],
        )
    )
    unsupported = assess(item, claim, catalog, DAY, conditions={"land.flag": True})
    assert unsupported.status is Applicability.UNRESOLVED
    with pytest.raises(ValueError, match="not_applicable"):
        ApplicabilityFinding(
            candidate_id="c", status=Applicability.NOT_APPLICABLE, reasons=["empty result"]
        )


def test_user_laws_add_and_hints_stay_candidates() -> None:
    catalog = catalog_with(("law-a", "v1"), ("law-user", "v1"), ("law-hint", "v1"))
    result = plan(
        catalog,
        FactStore(),
        [],
        user_laws=[ref("law-user")],
        hints=[ref("law-hint"), ref("law-ghost")],
    )
    sources = {c.ref.work_id: c.sources for c in result.candidates}
    assert sources["law-user"] == [CandidateSource.USER_SUPPLIED]
    assert sources["law-hint"] == [CandidateSource.EXTERNAL_HINT]
    assert all(c.status is Applicability.CANDIDATE for c in result.candidates)
    assert len(result.coverage) == len(plan(catalog, FactStore(), []).coverage)
    ghost = [u for u in result.unresolved if "law-ghost" in u.detail]
    assert ghost and not ghost[0].blocking


def test_candidates_follow_priority_order_and_merge_sources() -> None:
    catalog = catalog_with(("law-a", "v1"))
    store = FactStore()
    store.add(fact("designation.green", True))
    profile = ChecklistProfile(
        profile_id="t",
        version="1",
        law_families=["x"],
        items=[
            ChecklistItem(
                checklist_id="x",
                label="x",
                law_family="x",
                topic="use",
                targets=[ProvisionTarget(work_id="law-a", article=1)],
            )
        ],
    )
    result = plan(catalog, store, [link("green", "law-a", "use")], profile=profile)
    assert len(result.candidates) == 1
    assert result.candidates[0].sources == [
        CandidateSource.OFFICIAL_DESIGNATION_LINK,
        CandidateSource.REVIEWED_CATALOG,
    ]


def test_blocking_gap_withholds_permission_even_with_passes() -> None:
    passed = RuleEvaluationRecord(
        rule_version_id="r",
        candidate_id="c",
        outcome=Outcome.PASS,
        input_digest="d",
        reviewed=True,
    )
    row = CoverageItem(checklist_id="x", label="x", subject="p1", state="satisfied")
    gap = UnresolvedItem(item_id="g", kind="missing_document", detail="문서")
    assert summarize([row], [], [passed], [], [gap]).legacy_status == "insufficient_data"
    assert summarize([row], [], [passed], [], []).legacy_status == "permitted"
    conditional = summarize([row], [], [passed], [], [], remaining_procedures=["협의"])
    assert conditional.legacy_status == "conditionally_permitted"
    assert summarize([], [], [], [], []).legacy_status == "outside_scope"


def test_legacy_decision_matches_report_contract_rules() -> None:
    passed = RuleEvaluationRecord(
        rule_version_id="r",
        candidate_id="c",
        outcome=Outcome.PASS,
        input_digest="d",
        reviewed=True,
    )
    row = CoverageItem(checklist_id="x", label="x", subject="p1", state="satisfied")
    summary = summarize([row], [], [passed], [], [])
    assert legacy_decision(summary)["status"] == "insufficient_evidence"
    signed = legacy_decision(
        summary, reviewed_by="legal_reviewer", checks=[{"id": "x"}], scope={"profile": "t"}
    )
    assert signed["status"] == "permitted" and signed["reviewed_by"] == "legal_reviewer"


def test_fact_supersede_keeps_history_on_both_axes() -> None:
    store = FactStore()
    first = fact("land.area", 100, fact_id="a")
    later = NOW.replace(day=2)
    store.add(first)
    store.supersede("a", fact("land.area", 110, fact_id="b", recorded_at=later))
    assert store.current("land.area", "p1", DAY).value == 110
    assert store.current("land.area", "p1", DAY, as_of_recorded=NOW).value == 100
    assert [f.fact_id for f in store.history("land.area", "p1")] == ["a", "b"]


def test_provider_registry_respects_historical_support() -> None:
    current = FixtureProvider("now", "c/1", frozenset({"land"}), {})
    archive = FixtureProvider("archive", "c/1", frozenset({"land"}), {})
    registry = ProviderRegistry()
    registry.register(current, [ProviderProfile("land", max_concurrency=4)])
    registry.register(archive, [ProviderProfile("land", historical=True)])
    assert [p.name for p in registry.for_capability("land", historical=True)] == ["archive"]
    assert len(registry.for_capability("land")) == 2
    assert registry.concurrency("now") == 4
    assert current.fetch({"key": "missing"}).status is CollectionStatus.UNSUPPORTED
    with pytest.raises(ValueError, match="undeclared"):
        registry.register(FixtureProvider("x", "c/1", frozenset(), {}), [ProviderProfile("land")])


def test_provider_concurrency_limit_is_enforced() -> None:
    lock = threading.Lock()
    active = peak = 0
    barrier = threading.Event()

    def executor(node: RunNode) -> CollectionResult:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(0.05)
        with lock:
            active -= 1
        return _result(node, CollectionStatus.FOUND)

    engine = RunEngine(InMemoryRunStore(), {"p": executor}, concurrency={"p": 2})
    dag = RunDAG([RunNode(node_id=f"n{i}", provider="p") for i in range(6)])
    record = engine.execute(engine.create("proj", "r1", {}, dag).run_id)
    assert record.status is ExecutionStatus.COMPLETED and peak == 2


def test_dag_rejects_cycles_and_unknown_dependencies() -> None:
    with pytest.raises(ValueError, match="cycle"):
        RunDAG(
            [
                RunNode(node_id="a", provider="p", deps=["b"]),
                RunNode(node_id="b", provider="p", deps=["a"]),
            ]
        )
    with pytest.raises(ValueError, match="unknown"):
        RunDAG([RunNode(node_id="a", provider="p", deps=["ghost"])])


def test_resume_retries_only_what_needs_it() -> None:
    results = {"fail": CollectionStatus.FAILED, "auth": CollectionStatus.FAILED}
    calls: list[str] = []

    def executor(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        status = results.get(node.node_id, CollectionStatus.FOUND)
        kind = ErrorKind.AUTH if node.node_id == "auth" else ErrorKind.TRANSIENT
        extra = {"error_kind": kind} if status is CollectionStatus.FAILED else {}
        return _result(node, status, **extra)

    engine = RunEngine(InMemoryRunStore(), {"p": executor})
    dag = RunDAG([RunNode(node_id=n, provider="p") for n in ("ok", "fail", "auth")])
    run_id = engine.execute(engine.create("proj", "r1", {}, dag).run_id).run_id
    calls.clear()
    results.pop("fail")
    record = engine.resume(run_id)
    assert calls == ["fail"]
    assert record.nodes["auth"].status is ExecutionStatus.FAILED
    results.pop("auth")
    assert engine.resume(run_id, retry_blocked=True).status is ExecutionStatus.COMPLETED


def test_changed_input_reruns_the_node_and_its_dependents() -> None:
    calls: list[str] = []

    def executor(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        return _result(node, CollectionStatus.FOUND)

    engine = RunEngine(InMemoryRunStore(), {"p": executor})
    dag = RunDAG(
        [
            RunNode(node_id="a", provider="p", request={"v": 1}),
            RunNode(node_id="b", provider="p", deps=["a"]),
            RunNode(node_id="c", provider="p"),
        ]
    )
    run_id = engine.execute(engine.create("proj", "r1", {}, dag).run_id).run_id
    calls.clear()
    engine.resume(run_id, changed_requests={"a": {"v": 2}})
    assert calls == ["a", "b"]
