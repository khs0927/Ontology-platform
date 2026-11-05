"""Applicability assessment and conflict detection (W07/W09; scenarios S13, S17, S18).

A candidate moves to ``applicable`` or ``not_applicable`` only on known facts and a declared
condition. Everything else stays ``unresolved``. No law outranks another by a number here: a
conflict is classified only by a reviewed relation that cites its basis.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from archontos.review.facts import FactResolution, FactStore
from archontos.review.legal import LegalCatalog
from archontos.review.model import (
    Applicability,
    ApplicabilityFinding,
    CandidateProvision,
    Conflict,
    InterpretationReview,
    canonical_digest,
)


class ReviewedRelation(BaseModel):
    """A reviewed legal relation between provisions, e.g. EXCEPTS_UNDER with its basis."""

    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[str] = Field(min_length=2)
    kind: Literal["cumulative", "exception", "delegation", "special_rule", "transitional"]
    evidence_ids: list[str] = Field(min_length=1)
    review: InterpretationReview


def _usable(resolution: FactResolution) -> bool:
    return resolution.known and all(f.observation_scope == "whole" for f in resolution.facts)


def assess(
    candidate: CandidateProvision,
    facts: FactStore,
    catalog: LegalCatalog,
    day: date,
    *,
    conditions: Mapping[str, Any] | None = None,
    exception_facts: Mapping[str, str] | None = None,
) -> ApplicabilityFinding:
    """Assess one candidate.

    ``conditions`` maps a fact path to the value that triggers the provision. ``exception_facts``
    maps an exception provision key to the fact path that decides it.
    """

    version = catalog.version(candidate.ref.work_id, candidate.ref.version_id)
    in_force = version.effective.contains(day) if version else None
    if in_force is not True:
        return ApplicabilityFinding(
            candidate_id=candidate.candidate_id,
            status=Applicability.UNRESOLVED,
            reasons=[f"{candidate.ref.version_id}: 기준일 {day}의 시행 여부를 확정하지 못함"],
        )

    required = {*candidate.required_facts, *(conditions or {})}
    resolved = {path: facts.current(path, candidate.subject, day) for path in sorted(required)}
    missing = [path for path, item in resolved.items() if not _usable(item)]
    fact_ids = sorted({fid for item in resolved.values() for fid in item.fact_ids})
    evidence_ids = sorted({eid for item in resolved.values() for eid in item.evidence_ids})

    open_exceptions: list[str] = []
    for exception in candidate.exceptions_to_check:
        path = (exception_facts or {}).get(exception.key)
        decided = facts.current(path, candidate.subject, day) if path else None
        # Only a known False closes an exception; True still needs a reviewed reading of it.
        if decided is None or not _usable(decided) or decided.value is not False:
            open_exceptions.append(exception.key)

    base: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "fact_ids": fact_ids,
        "evidence_ids": evidence_ids,
        "missing_facts": missing,
        "unresolved_exceptions": open_exceptions,
    }
    if missing or open_exceptions:
        reasons = [f"필수 사실 미확인: {path}" for path in missing]
        reasons += [f"예외 미확인: {key}" for key in open_exceptions]
        return ApplicabilityFinding(status=Applicability.UNRESOLVED, reasons=reasons, **base)
    if not conditions:
        return ApplicabilityFinding(
            status=Applicability.UNRESOLVED, reasons=["검토된 적용조건이 없음"], **base
        )

    unmet = sorted(path for path, value in conditions.items() if resolved[path].value != value)
    if not unmet:
        return ApplicabilityFinding(
            status=Applicability.APPLICABLE, reasons=["적용조건 충족"], **base
        )
    if evidence_ids and fact_ids:
        return ApplicabilityFinding(
            status=Applicability.NOT_APPLICABLE,
            reasons=[f"적용조건 불충족: {path}" for path in unmet],
            **base,
        )
    return ApplicabilityFinding(
        status=Applicability.UNRESOLVED,
        reasons=[f"근거 없는 사실로 비해당 판단 불가: {path}" for path in unmet],
        **base,
    )


def _periods_overlap(a: CandidateProvision, b: CandidateProvision, catalog: LegalCatalog) -> bool:
    first = catalog.version(a.ref.work_id, a.ref.version_id)
    second = catalog.version(b.ref.work_id, b.ref.version_id)
    if first is None or second is None:
        return True  # undecidable: keep it visible rather than dropping a possible conflict
    x, y = first.effective, second.effective
    starts_before_end = y.valid_to is None or x.valid_from is None or x.valid_from < y.valid_to
    ends_after_start = x.valid_to is None or y.valid_from is None or y.valid_from < x.valid_to
    return starts_before_end and ends_after_start


def detect_conflicts(
    candidates: Sequence[CandidateProvision],
    findings: Sequence[ApplicabilityFinding],
    *,
    catalog: LegalCatalog | None = None,
    positions: Mapping[str, Any] | None = None,
    reviewed: Sequence[ReviewedRelation] = (),
) -> list[Conflict]:
    """Pair provisions on the same subject, topic and period.

    Different topics are parallel limits and never conflict (S18). ``positions`` holds each
    candidate's normative content: a difference needs both sides stated, and equal content is no
    conflict. Both sides stay in the result (S17); only a reviewed relation changes the kind.
    """

    negative = {
        finding.candidate_id
        for finding in findings
        if finding.status is Applicability.NOT_APPLICABLE
    }
    groups: dict[tuple[str, str], list[CandidateProvision]] = defaultdict(list)
    for candidate in candidates:
        if candidate.candidate_id not in negative:
            groups[(candidate.subject, candidate.topic)].append(candidate)

    conflicts: list[Conflict] = []
    known = positions or {}
    for (subject, topic), members in sorted(groups.items()):
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                pair = sorted([first.candidate_id, second.candidate_id])
                left, right = known.get(pair[0]), known.get(pair[1])
                if first.ref.work_id == second.ref.work_id:
                    continue
                if left is None or right is None or left == right:
                    continue
                if catalog is not None and not _periods_overlap(first, second, catalog):
                    continue
                relation = next(
                    (
                        item
                        for item in reviewed
                        if item.review is InterpretationReview.APPROVED
                        and set(pair) <= set(item.candidate_ids)
                    ),
                    None,
                )
                conflicts.append(
                    Conflict(
                        conflict_id="conflict:" + canonical_digest([subject, topic, pair])[:16],
                        topic=topic,
                        subject=subject,
                        candidate_ids=pair,
                        kind=relation.kind if relation else "unresolved",
                        basis_evidence_ids=list(relation.evidence_ids) if relation else [],
                        note=(
                            "검토된 관계로 구분됨"
                            if relation
                            else "같은 대상·주제·기간의 상충: 근거 없이 승자를 정하지 않음"
                        ),
                    )
                )
    return conflicts
