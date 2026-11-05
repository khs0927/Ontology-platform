"""Scope checklist and candidate discovery (W07; scenarios S04-S10, S18).

Candidates come from official designation links first, then the reviewed checklist, reference
expansion and finally additive user or external hints. A candidate is only "worth checking":
applicability is decided later, and a mandatory checklist row may never be silently dropped.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from archontos.review.facts import FactStore
from archontos.review.legal import LegalCatalog, expand_references
from archontos.review.model import (
    CandidateProvision,
    CandidateSource,
    CoverageItem,
    FactStatus,
    NextTask,
    Proposal,
    ProvisionRef,
    ReviewScope,
    Site,
    UnresolvedItem,
    canonical_digest,
)

SOURCE_ORDER = list(CandidateSource)
DEFAULT_PROFILE_ID = "kr-landuse-building"
DEFAULT_PROFILE_VERSION = "2026.11-draft"


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProvisionTarget(_Spec):
    """A provision position without a version: bound to a version at the governing date."""

    work_id: str = Field(min_length=1)
    kind: str = "article"
    article: int | None = None
    branch: int | None = None
    paragraph: int | None = None
    item: int | None = None
    item_branch: int | None = None
    sub_item: str | None = None
    annex_no: str | None = None
    addendum_key: str | None = None

    def bind(self, version_id: str) -> ProvisionRef:
        return ProvisionRef.model_validate(
            {**self.model_dump(exclude_none=True), "version_id": version_id}
        )


class DesignationLink(_Spec):
    """One row of the official designation x jurisdiction x action table."""

    designation: str = Field(min_length=1)  # fact path suffix: designation.<code>
    jurisdiction_code: str | None = None  # None: national
    action: str | None = None  # None: any action
    target: ProvisionTarget
    topic: str
    required_facts: list[str] = Field(default_factory=list)
    exceptions: list[ProvisionTarget] = Field(default_factory=list)
    source_version: str | None = None  # official file/API version the row came from


class ChecklistItem(_Spec):
    checklist_id: str
    label: str
    law_family: str
    topic: str
    actions: list[str] = Field(default_factory=list)  # empty: every action
    uses: list[str] = Field(default_factory=list)  # empty: every use
    targets: list[ProvisionTarget] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    trigger_designation: str | None = None  # the row applies once this designation is raised
    required_documents: list[str] = Field(default_factory=list)  # document.<id> facts
    jurisdictional: bool = False  # needs a confirmed local jurisdiction (ordinance rows)
    mandatory: bool = True


class ChecklistProfile(_Spec):
    profile_id: str
    version: str
    reviewed: bool = False  # True only after a named legal reviewer signed the profile
    law_families: list[str]
    excluded: list[str] = Field(default_factory=list)
    items: list[ChecklistItem]

    def scope(self, *, max_reference_depth: int = 4) -> ReviewScope:
        return ReviewScope(
            profile_id=self.profile_id,
            profile_version=self.version,
            law_families=list(self.law_families),
            excluded=list(self.excluded),
            max_reference_depth=max_reference_depth,
        )


def _row(checklist_id: str, label: str, family: str, topic: str, **extra: Any) -> dict[str, Any]:
    return {
        "checklist_id": checklist_id,
        "label": label,
        "law_family": family,
        "topic": topic,
        **extra,
    }


def default_profile() -> ChecklistProfile:
    """The shipped checklist structure.

    It carries no provision targets: official IDs are pinned by W03 and supplied as a profile
    file, so until then every row reports an open gap instead of a satisfied scope.
    """

    return ChecklistProfile.model_validate(
        {
            "profile_id": DEFAULT_PROFILE_ID,
            "version": DEFAULT_PROFILE_VERSION,
            "reviewed": False,
            "law_families": [
                "nlupa",
                "building_act",
                "farmland",
                "mountain",
                "ordinance",
                "district_plan",
                "other_law",
            ],
            "excluded": ["프로필에 없는 법규: 대한민국 전체 규제 검토를 뜻하지 않음"],
            "items": [
                _row(
                    "nlupa.use_zone",
                    "국토계획법 용도지역 행위 제한",
                    "nlupa",
                    "use_permission",
                    required_facts=["designation.query_complete"],
                ),
                _row(
                    "nlupa.development_permit",
                    "개발행위허가 대상 확인",
                    "nlupa",
                    "development_permit",
                    actions=["land_form_change", "new_construction"],
                ),
                _row(
                    "building.permit",
                    "건축법 허가·신고 절차",
                    "building_act",
                    "building_permit",
                    actions=["new_construction", "use_change"],
                ),
                _row(
                    "farmland.conversion",
                    "농지 전용·일시사용 절차",
                    "farmland",
                    "farmland_conversion",
                    required_facts=["legal.is_farmland"],
                ),
                _row(
                    "mountain.conversion",
                    "산지 전용·일시사용 절차",
                    "mountain",
                    "mountain_conversion",
                    required_facts=["legal.is_mountain_land"],
                ),
                _row(
                    "ordinance.local",
                    "관할 조례 위임 사항",
                    "ordinance",
                    "local_ordinance",
                    jurisdictional=True,
                ),
                _row(
                    "district_plan.decision",
                    "지구단위계획 결정조서·도면",
                    "district_plan",
                    "district_plan",
                    trigger_designation="district_unit_plan",
                    required_documents=["district_plan_decision", "district_plan_drawing"],
                ),
                _row(
                    "other_law.overlay",
                    "다른 법률 지정 범위 확인",
                    "other_law",
                    "other_law_overlay",
                    required_facts=["other_law.query_complete"],
                ),
            ],
        }
    )


class CandidatePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[CandidateProvision] = Field(default_factory=list)
    coverage: list[CoverageItem] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
    tasks: list[NextTask] = Field(default_factory=list)


class _Builder:
    def __init__(self) -> None:
        self.candidates: dict[str, CandidateProvision] = {}
        self.unresolved: dict[str, UnresolvedItem] = {}
        self.tasks: dict[str, NextTask] = {}

    def candidate(
        self,
        ref: ProvisionRef,
        *,
        topic: str,
        subject: str,
        source: CandidateSource,
        reason: str,
        required_facts: Iterable[str] = (),
        exceptions: Iterable[ProvisionRef] = (),
        mandatory: bool = False,
    ) -> str:
        candidate_id = "cand:" + canonical_digest([ref.key, topic, subject])[:16]
        existing = self.candidates.get(candidate_id)
        if existing is None:
            existing = CandidateProvision(
                candidate_id=candidate_id,
                ref=ref,
                topic=topic,
                subject=subject,
                sources=[source],
                reasons=[reason],
            )
            self.candidates[candidate_id] = existing
        if source not in existing.sources:
            existing.sources.append(source)
            existing.sources.sort(key=SOURCE_ORDER.index)
        if reason not in existing.reasons:
            existing.reasons.append(reason)
        existing.required_facts = sorted({*existing.required_facts, *required_facts})
        known = {item.key for item in existing.exceptions_to_check}
        existing.exceptions_to_check.extend(e for e in exceptions if e.key not in known)
        existing.mandatory = existing.mandatory or mandatory
        return candidate_id

    def gap(
        self,
        kind: Any,
        detail: str,
        *,
        subject: str | None,
        role: Any,
        target: str,
        blocking: bool = True,
    ) -> str:
        item_id = "gap:" + canonical_digest([kind, subject, target])[:16]
        task_id = "task:" + item_id[4:]
        self.unresolved.setdefault(
            item_id,
            UnresolvedItem(
                item_id=item_id,
                kind=kind,
                subject=subject,
                detail=detail,
                blocking=blocking,
                task_id=task_id,
            ),
        )
        self.tasks.setdefault(
            task_id,
            NextTask(task_id=task_id, role=role, reason=detail, target=target, resolves=[item_id]),
        )
        return item_id


def _subjects(site: Site, proposal: Proposal) -> list[str]:
    return [part.part_id for part in site.parts] or list(site.pnus) or [proposal.project_id]


def _bind(
    catalog: LegalCatalog,
    target: ProvisionTarget,
    day: date,
    builder: _Builder,
    subject: str,
) -> ProvisionRef | str:
    """A version-bound ref, or the id of the gap explaining why there is none."""

    resolution = catalog.resolve_version(target.work_id, day)
    if resolution.version is None:
        return builder.gap(
            "temporal_unresolved",
            f"{target.work_id}: {resolution.reason}",
            subject=subject,
            role="data_operator",
            target=f"{target.work_id} version on {day}",
        )
    return target.bind(resolution.version.version_id)


def _applicable_links(
    links: Sequence[DesignationLink], code: str, proposal: Proposal, jurisdiction: str | None
) -> list[DesignationLink]:
    return [
        link
        for link in links
        if link.designation == code
        and (link.action is None or link.action in proposal.actions)
        and (link.jurisdiction_code is None or link.jurisdiction_code == jurisdiction)
    ]


def _designation_candidates(
    builder: _Builder,
    site: Site,
    proposal: Proposal,
    facts: FactStore,
    links: Sequence[DesignationLink],
    catalog: LegalCatalog,
    day: date,
) -> set[str]:
    raised: set[str] = set()
    for subject in _subjects(site, proposal):
        for path in facts.paths(subject):
            if not path.startswith("designation.") or path == "designation.query_complete":
                continue
            code = path.removeprefix("designation.")
            resolution = facts.current(path, subject, day)
            if resolution.status in {FactStatus.UNKNOWN, FactStatus.DISPUTED}:
                builder.gap(
                    "missing_fact",
                    f"지정 {code} 미확정: {resolution.reason}",
                    subject=subject,
                    role="data_operator",
                    target=path,
                )
                continue
            if resolution.value is False:
                continue
            raised.add(code)
            matched = _applicable_links(links, code, proposal, site.jurisdiction_code)
            if not matched:
                builder.gap(
                    "unsupported_source",
                    f"지정 {code}에 연결된 공식 조문 자료 없음",
                    subject=subject,
                    role="data_operator",
                    target=f"designation link for {code}",
                )
            for link in matched:
                ref = _bind(catalog, link.target, day, builder, subject)
                if isinstance(ref, str):
                    continue
                exceptions = [
                    bound
                    for target in link.exceptions
                    if isinstance(
                        bound := _bind(catalog, target, day, builder, subject), ProvisionRef
                    )
                ]
                builder.candidate(
                    ref,
                    topic=link.topic,
                    subject=subject,
                    source=CandidateSource.OFFICIAL_DESIGNATION_LINK,
                    reason=f"지정 {code}의 공식 연결({link.source_version or '버전 미기재'})",
                    required_facts=link.required_facts,
                    exceptions=exceptions,
                    mandatory=True,
                )
    return raised


def _matches(item: ChecklistItem, proposal: Proposal) -> bool:
    actions_ok = not item.actions or bool(set(item.actions) & set(proposal.actions))
    uses_ok = not item.uses or bool(set(item.uses) & set(proposal.uses))
    return actions_ok and uses_ok


def _coverage_row(
    builder: _Builder,
    item: ChecklistItem,
    subject: str,
    site: Site,
    facts: FactStore,
    catalog: LegalCatalog,
    day: date,
) -> CoverageItem:
    candidate_ids: list[str] = []
    gaps: list[str] = []
    if item.jurisdictional and not site.jurisdiction_code:
        gaps.append(
            builder.gap(
                "missing_fact",
                f"{item.label}: 관할 미확정",
                subject=subject,
                role="user",
                target="site.jurisdiction_code",
            )
        )
    for target in item.targets:
        ref = _bind(catalog, target, day, builder, subject)
        if isinstance(ref, str):
            gaps.append(ref)
            continue
        version = catalog.version(ref.work_id, ref.version_id)
        local = version.jurisdiction_code if version else None
        if local is not None and local != site.jurisdiction_code:
            continue  # S08: a same-named ordinance of another jurisdiction
        candidate_ids.append(
            builder.candidate(
                ref,
                topic=item.topic,
                subject=subject,
                source=CandidateSource.REVIEWED_CATALOG,
                reason=f"체크리스트 {item.checklist_id}: {item.label}",
                required_facts=item.required_facts,
                mandatory=item.mandatory,
            )
        )
    if not candidate_ids and not gaps:
        gaps.append(
            builder.gap(
                "unsupported_source",
                f"{item.label}: 이 범위의 조문이 카탈로그에 없음",
                subject=subject,
                role="data_operator",
                target=f"catalog provisions for {item.checklist_id}",
            )
        )
    for document in item.required_documents:
        path = f"document.{document}"
        if not facts.current(path, subject, day).known:
            gaps.append(
                builder.gap(
                    "missing_document",
                    f"{item.label}: 필수 문서 {document} 미수집",
                    subject=subject,
                    role="user",
                    target=path,
                )
            )
    return CoverageItem(
        checklist_id=item.checklist_id,
        label=item.label,
        subject=subject,
        state="unresolved" if gaps else "satisfied",
        candidate_ids=candidate_ids,
        unresolved_ids=gaps,
    )


def _expand(builder: _Builder, scope: ReviewScope, catalog: LegalCatalog) -> None:
    for candidate in list(builder.candidates.values()):
        expansion = expand_references(catalog, [candidate.ref], scope.max_reference_depth)
        for provision in expansion.provisions:
            if provision.ref.key == candidate.ref.key:
                continue
            builder.candidate(
                provision.ref,
                topic=candidate.topic,
                subject=candidate.subject,
                source=CandidateSource.REFERENCE_EXPANSION,
                reason=f"{candidate.ref.key}의 참조 조문",
                mandatory=candidate.mandatory,
            )
            if provision.ref.key not in {r.key for r in candidate.required_references}:
                candidate.required_references.append(provision.ref)
        for ref in expansion.unresolved:
            builder.gap(
                "unresolved_reference",
                f"참조 조문 미수집: {ref.key}",
                subject=candidate.subject,
                role="data_operator",
                target=ref.key,
            )
        for ref in expansion.capped_refs:
            builder.gap(
                "unresolved_reference",
                f"참조 깊이 상한 {scope.max_reference_depth} 도달: {ref.key}",
                subject=candidate.subject,
                role="data_operator",
                target=ref.key,
            )


def _additive(
    builder: _Builder,
    catalog: LegalCatalog,
    refs: Sequence[ProvisionRef],
    source: CandidateSource,
    subject: str,
    label: str,
) -> None:
    for ref in refs:
        if catalog.get(ref) is None:
            builder.gap(
                "unresolved_reference",
                f"{label} 조문을 원문으로 확인하지 못함: {ref.key}",
                subject=subject,
                role="data_operator",
                target=ref.key,
                blocking=False,
            )
            continue
        builder.candidate(
            ref, topic="additional", subject=subject, source=source, reason=f"{label} 지정"
        )


def generate_candidates(
    scope: ReviewScope,
    site: Site,
    proposal: Proposal,
    facts: FactStore,
    links: Sequence[DesignationLink],
    catalog: LegalCatalog,
    user_laws: Sequence[ProvisionRef] = (),
    hints: Sequence[ProvisionRef] = (),
    *,
    day: date,
    profile: ChecklistProfile | None = None,
) -> CandidatePlan:
    """Build the candidate plan for ``scope``; see the module docstring for the priority order."""

    active = profile or default_profile()
    builder = _Builder()
    if not site.resolved:
        builder.gap(
            "site_ambiguous",
            f"주소 후보 {len(site.candidates)}건: 필지를 선택해야 함",
            subject=site.address,
            role="user",
            target="site selection",
        )
    subjects = _subjects(site, proposal)
    raised = _designation_candidates(builder, site, proposal, facts, links, catalog, day)
    coverage = [
        _coverage_row(builder, item, subject, site, facts, catalog, day)
        for item in active.items
        if _matches(item, proposal)
        and (item.trigger_designation is None or item.trigger_designation in raised)
        for subject in subjects
    ]
    _expand(builder, scope, catalog)
    _additive(builder, catalog, user_laws, CandidateSource.USER_SUPPLIED, subjects[0], "사용자")
    _additive(builder, catalog, hints, CandidateSource.EXTERNAL_HINT, subjects[0], "외부 힌트")

    shared_access = any(
        facts.current("site.shared_access", name, day).value is True for name in subjects
    )
    if len(site.pnus) > 1 or shared_access:
        builder.gap(
            "scope_expansion",
            "여러 필지·공유 진입도로: 원필지 밖 영향 범위 확인 필요",
            subject=site.address or subjects[0],
            role="user",
            target="adjacent parcels and shared access",
        )

    ordered = sorted(
        builder.candidates.values(),
        key=lambda c: (SOURCE_ORDER.index(c.sources[0]), c.ref.key, c.subject),
    )
    return CandidatePlan(
        candidates=ordered,
        coverage=coverage,
        unresolved=list(builder.unresolved.values()),
        tasks=list(builder.tasks.values()),
    )
