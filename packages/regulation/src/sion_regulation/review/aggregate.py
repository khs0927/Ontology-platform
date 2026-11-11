"""Project summary and legacy report mapping (framework plan section 14; S13, S20).

A rule result stays PASS/FAIL/REVIEW. The summary adds what is confirmed, what is open and whether
the declared scope was met; one blocking open item is enough to withhold ``permitted``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sion_regulation.review.model import (
    Applicability,
    ApplicabilityFinding,
    Conflict,
    CoverageItem,
    Outcome,
    ReviewSummary,
    RuleEvaluationRecord,
    UnresolvedItem,
)

LegacyStatus = Literal[
    "permitted",
    "conditionally_permitted",
    "not_permitted",
    "insufficient_data",
    "conflict",
    "outside_scope",
]

# ReviewSummary.legacy_status -> decision.status of building-regulation-report/1.
LEGACY_REPORT_STATUS = {
    "permitted": "permitted",
    "conditionally_permitted": "conditionally_permitted",
    "not_permitted": "not_permitted",
    "insufficient_data": "insufficient_evidence",
    "conflict": "conflicting_evidence",
    "outside_scope": "outside_scope",
}


def summarize(
    coverage: Sequence[CoverageItem],
    findings: Sequence[ApplicabilityFinding],
    evaluations: Sequence[RuleEvaluationRecord],
    conflicts: Sequence[Conflict],
    unresolved: Sequence[UnresolvedItem],
    *,
    remaining_procedures: Sequence[str] = (),
) -> ReviewSummary:
    fails = [e for e in evaluations if e.outcome is Outcome.FAIL and e.reviewed]
    passes = [e for e in evaluations if e.outcome is Outcome.PASS and e.reviewed]
    reviews = [e for e in evaluations if e.outcome is Outcome.REVIEW]
    blocking = [item for item in unresolved if item.blocking]
    open_findings = [
        f for f in findings if f.status in {Applicability.UNRESOLVED, Applicability.CANDIDATE}
    ]
    open_conflicts = [c for c in conflicts if c.kind == "unresolved"]
    scope_satisfied = bool(coverage) and all(item.state == "satisfied" for item in coverage)
    has_unresolved = bool(blocking or open_findings or reviews or open_conflicts)

    codes: list[str] = []
    if fails:
        codes.append("CONFIRMED_NONCONFORMITY")
    if blocking:
        codes.append("BLOCKING_UNRESOLVED_ITEMS")
    if open_findings:
        codes.append("APPLICABILITY_UNRESOLVED")
    if reviews:
        codes.append("RULE_REVIEW_REQUIRED")
    if open_conflicts:
        codes.append("UNRESOLVED_CONFLICT")
    if coverage and not scope_satisfied:
        codes.append("DECLARED_SCOPE_NOT_SATISFIED")
    if not passes and not fails:
        codes.append("NO_REVIEWED_RULE_RESULT")

    status: LegacyStatus
    if not coverage:
        status = "outside_scope"
        codes.append("NO_DECLARED_SCOPE_COVERAGE")
    elif fails:
        status = "not_permitted"
    elif open_conflicts:
        status = "conflict"
    elif has_unresolved or not scope_satisfied or not passes:
        status = "insufficient_data"
    elif remaining_procedures:
        status = "conditionally_permitted"
    else:
        status = "permitted"
    return ReviewSummary(
        has_confirmed_nonconformity=bool(fails),
        has_unresolved=has_unresolved,
        scope_satisfied=scope_satisfied,
        remaining_procedures=list(remaining_procedures),
        legacy_status=status,
        reason_codes=codes,
        advisory=True,
    )


def legacy_decision(
    summary: ReviewSummary,
    *,
    reviewed_by: str | None = None,
    checks: Sequence[dict[str, Any]] = (),
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``decision`` object of building-regulation-report/1.

    The report contract needs a reviewer, checks and scope for every definite status. Without them
    the decision falls back to ``insufficient_evidence``.
    """

    status = LEGACY_REPORT_STATUS[summary.legacy_status]
    definite = status in {"permitted", "conditionally_permitted", "not_permitted"}
    if definite and not (reviewed_by and checks and scope is not None):
        return {
            "status": "insufficient_evidence",
            "reason_codes": [*summary.reason_codes, "REVIEWER_RECORD_MISSING"],
        }
    decision: dict[str, Any] = {"status": status, "reason_codes": list(summary.reason_codes)}
    if definite:
        decision.update({"reviewed_by": reviewed_by, "checks": list(checks), "scope": scope})
    return decision
