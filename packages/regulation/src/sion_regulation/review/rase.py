"""RASE rule template and compilation to the rule-engine DSL (W09; S13, S21, D07).

Requirement / Applicability / Selection / Exception authoring on top of the existing safe compiler.
Anything the table below does not support stays REVIEW. Expressions are data: nothing is evaluated
as code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from archontos.domain.enums import DecisionOutcome
from archontos.rules.compiler import RuleCompilationError, compile_requirement
from archontos.rules.engine import RuleEvaluationError, evaluate_rule
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sion_regulation.review.model import (
    InterpretationReview,
    Outcome,
    ProvisionRef,
    RuleEvaluationRecord,
    canonical_digest,
)

SUPPORT_TABLE: dict[str, str] = {
    "comparison": "supported",  # ==, !=, >=, <=, >, <, in on one fact
    "selection_all": "supported",  # conjunction of comparisons as a precondition
    "exception_flag": "supported",  # comparison that lifts the requirement; unknown => REVIEW
    "calculation": "unsupported",  # derived quantities
    "nested_rase": "unsupported",  # a requirement that contains another requirement
    "mutatis_mutandis": "unsupported",  # 준용
    "procedure": "unsupported",  # procedural duties have no comparison form
    "transitional": "unsupported",  # 부칙 경과조치
}

Operator = Literal["==", "!=", ">=", "<=", ">", "<", "in"]
_EXEMPT_PATH = "rase.exempted"


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Clause(_Spec):
    fact_path: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    operator: Operator
    value: Any
    unit: str | None = None


class FactBinding(_Spec):
    path: str
    unit: str | None = None
    sources: list[str] = Field(default_factory=list)
    allowed_methods: list[str] = Field(default_factory=list)


class RuleBasis(_Spec):
    ref: ProvisionRef
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: dict[str, Any] = Field(default_factory=dict)
    source_kind: Literal["text", "table", "ocr"] = "text"
    span_verified: bool = False  # a person compared the value with the located original


class RuleReview(_Spec):
    author_role: str
    reviewer_role: str | None = None
    status: InterpretationReview = InterpretationReview.UNREVIEWED
    reviewed_on: date | None = None


class RuleTest(_Spec):
    name: str
    facts: dict[str, Any]
    expected: Outcome | None  # None: rule out of scope for these facts


class RaseRule(_Spec):
    rule_version_id: str = Field(min_length=1)
    basis: RuleBasis
    topic: str
    jurisdiction_code: str = Field(min_length=1)
    use_groups: list[str] = Field(default_factory=list)
    requirement: Clause
    selection: list[Clause] = Field(default_factory=list)
    exceptions: list[Clause] = Field(default_factory=list)
    fact_bindings: list[FactBinding] = Field(default_factory=list)
    interpretation: str = ""
    review: RuleReview
    tests: list[RuleTest] = Field(default_factory=list)
    features: list[str] = Field(default_factory=lambda: ["comparison"])

    @model_validator(mode="after")
    def _approval_has_basis(self) -> RaseRule:
        if self.review.status is InterpretationReview.APPROVED:
            if not self.review.reviewer_role or not self.review.reviewed_on:
                raise ValueError("an approved rule names its reviewer role and date")
            if self.review.reviewer_role == self.review.author_role:
                raise ValueError("author and reviewer roles must differ")
            if self.basis.source_kind != "text" and not self.basis.span_verified:
                raise ValueError("table/OCR values need a verified source span before approval")
        return self


@dataclass(frozen=True, slots=True)
class Unsupported:
    features: tuple[str, ...]
    reason: str


def _expr(clause: Clause) -> dict[str, Any]:
    return {clause.operator: [{"var": clause.fact_path}, {"literal": clause.value}]}


def compile_rase(rule: RaseRule) -> dict[str, Any] | Unsupported:
    """Compile to the engine JSON DSL, or return :class:`Unsupported`."""

    features = set(rule.features)
    if rule.selection:
        features.add("selection_all")
    if rule.exceptions:
        features.add("exception_flag")
    blocked = sorted(f for f in features if SUPPORT_TABLE.get(f) != "supported")
    if blocked:
        return Unsupported(tuple(blocked), f"unsupported rule features: {', '.join(blocked)}")

    payload: dict[str, Any] = {
        "fact_path": rule.requirement.fact_path,
        "operator": rule.requirement.operator,
        "value": rule.requirement.value,
        "title": rule.rule_version_id,
    }
    if rule.requirement.unit:
        payload["unit"] = rule.requirement.unit
    applicability: dict[str, Any] = {}
    if rule.use_groups:
        applicability["building_use_groups"] = list(rule.use_groups)
    if rule.selection:
        applicability["conditions"] = [_expr(clause) for clause in rule.selection]
    payload["applicability"] = applicability
    try:
        compiled = compile_requirement(
            natural_language=rule.interpretation or rule.topic,
            structured_payload=payload,
            jurisdiction_code=rule.jurisdiction_code,
        )
    except RuleCompilationError as exc:
        return Unsupported(("comparison",), str(exc))

    document = dict(compiled.logic_expr)
    units = dict(document.get("fact_units", {}))
    for clause in (*rule.selection, *rule.exceptions):
        if clause.unit:
            units[clause.fact_path] = clause.unit
    if units:
        document["fact_units"] = units
    if rule.exceptions:
        body = dict(document["rule"])
        body["if"] = {"or": [{"var": [_EXEMPT_PATH, False]}, body["if"]]}
        document["rule"] = body
        document["exceptions"] = [
            {"condition": _expr(clause), "override": {_EXEMPT_PATH: True}}
            for clause in rule.exceptions
        ]
    return document


def evaluate_candidate(
    rule: RaseRule,
    facts: dict[str, Any],
    *,
    candidate_id: str,
    fact_ids: list[str] | None = None,
    current_snapshot_hash: str | None = None,
) -> RuleEvaluationRecord:
    """Evaluate one rule. An unreviewed, unsupported or stale rule answers REVIEW."""

    digest = canonical_digest({"rule": rule.rule_version_id, "facts": facts})

    def record(
        outcome: Outcome,
        reason: str | None,
        *,
        reviewed: bool = True,
        details: dict[str, Any] | None = None,
    ) -> RuleEvaluationRecord:
        return RuleEvaluationRecord(
            rule_version_id=rule.rule_version_id,
            candidate_id=candidate_id,
            outcome=outcome,
            reason=reason,
            fact_ids=fact_ids or [],
            input_digest=digest,
            reviewed=reviewed,
            details=details or {},
        )

    if rule.review.status is not InterpretationReview.APPROVED:
        reason = f"rule not approved: {rule.review.status.value}"
        return record(Outcome.REVIEW, reason, reviewed=False)
    if current_snapshot_hash is not None and current_snapshot_hash != rule.basis.snapshot_hash:
        reason = "basis text changed since the rule was reviewed"
        return record(Outcome.REVIEW, reason, reviewed=False)
    document = compile_rase(rule)
    if isinstance(document, Unsupported):
        details = {"unsupported": list(document.features)}
        return record(Outcome.REVIEW, document.reason, reviewed=False, details=details)
    try:
        result = evaluate_rule(document, facts)
    except RuleEvaluationError as exc:
        return record(Outcome.REVIEW, f"rule could not be evaluated: {exc}")
    if not result.applicable or result.outcome is None:
        reason = result.reason or "rule scope not matched"
        return record(Outcome.REVIEW, reason, details={"rule_applicable": False})
    outcome = {
        DecisionOutcome.PASS: Outcome.PASS,
        DecisionOutcome.FAIL: Outcome.FAIL,
        DecisionOutcome.REVIEW: Outcome.REVIEW,
    }[result.outcome]
    return record(outcome, result.reason, details=dict(result.details))


def run_rule_tests(rule: RaseRule) -> list[str]:
    """Run the rule's own cases through the engine; returns the failures."""

    document = compile_rase(rule)
    if isinstance(document, Unsupported):
        return [document.reason]
    failures: list[str] = []
    for case in rule.tests:
        result = evaluate_rule(document, case.facts)
        actual = result.outcome.value if result.outcome else None
        expected = case.expected.value if case.expected else None
        if actual != expected:
            failures.append(f"{case.name}: expected {expected}, got {actual}")
    return failures
