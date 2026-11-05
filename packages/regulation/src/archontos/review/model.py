"""Shared domain model for the overlapping building/land regulation review workflow.

Implements the state axes and objects of docs/regulation/regulation-framework-plan-2026-10-11.md
sections 6-8 and 12-14. Every module in ``archontos.review`` builds on these types; change them
only together with their consumers and tests.

Invariants enforced here (and relied on everywhere else):

* An empty / failed / truncated collection is never a negative fact (section 7).
* ``candidate`` is not ``applicable``; a run ``completed`` is not "legal review complete".
* Legal validity (``valid_from``/``valid_to``) and system knowledge time
  (``recorded_at``/``superseded_at``) are separate axes.
* A legal-work identity (``work_id``) is separate from a version identity (``version_id``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "archontos-regulation-review/1"


# --------------------------------------------------------------------------- state axes


class CollectionStatus(StrEnum):
    """Data supply result. Only FOUND carries positive data; nothing here is a negative fact."""

    PENDING = "pending"
    FOUND = "found"
    EMPTY = "empty"
    FAILED = "failed"
    TRUNCATED = "truncated"
    UNSUPPORTED = "unsupported"


class FactStatus(StrEnum):
    OBSERVED = "observed"
    ASSERTED = "asserted"
    CORROBORATED = "corroborated"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class Applicability(StrEnum):
    CANDIDATE = "candidate"
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


class InterpretationReview(StrEnum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONTESTED = "contested"


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Outcome(StrEnum):
    PASS = "PASS"  # noqa: S105 - decision outcome, not a credential
    FAIL = "FAIL"
    REVIEW = "REVIEW"


class ErrorKind(StrEnum):
    """Provider failure taxonomy (framework plan section 12)."""

    TRANSIENT = "transient"  # network / 5xx: bounded retry
    RATE_LIMITED = "rate_limited"  # 429: honour Retry-After, run becomes partial
    AUTH = "auth"  # 401/403: no retry storm, create an ops task
    SCHEMA = "schema"  # invalid shape / provision mismatch: quarantine
    TIMEOUT = "timeout"  # keep partial results, offer resume
    CANCELLED = "cancelled"


class RelationLayer(StrEnum):
    """Three relation layers of section 6; only REVIEWED_LEGAL may feed evaluation."""

    DATA = "data"  # HAS_VERSION, CONTAINS, INTERSECTS, DESIGNATED_BY, ISSUED_BY
    CANDIDATE = "candidate"  # REFERENCES, POSSIBLY_RELEVANT, DEFINES, REQUIRES_FACT
    REVIEWED_LEGAL = (
        "reviewed_legal"  # APPLIES_UNDER, DELEGATES_UNDER, EXCEPTS_UNDER, PREVAILS_UNDER
    )


class CandidateSource(StrEnum):
    """Why a provision was proposed, in the priority order of section 8.2."""

    OFFICIAL_DESIGNATION_LINK = (
        "official_designation_link"  # 1. designation x jurisdiction x action
    )
    REVIEWED_CATALOG = "reviewed_catalog"  # 2. reviewed checklist for use/action
    REFERENCE_EXPANSION = "reference_expansion"  # 3. delegation/definition/annex/applies-mutatis
    RELATED_SEARCH = "related_search"  # 4. related-law search / keywords
    USER_SUPPLIED = "user_supplied"  # user-named law: additive only
    EXTERNAL_HINT = "external_hint"  # external MCP priority hint: candidate only


# --------------------------------------------------------------------------- helpers


def canonical_digest(payload: Any) -> str:
    """Deterministic sha256 hex digest of JSON-compatible data (sorted keys, no whitespace)."""

    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class Interval(_Model):
    """Legal validity interval; ``valid_to`` is exclusive, ``None`` is open-ended."""

    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Interval:
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self

    def contains(self, day: date) -> bool | None:
        """True/False when decidable; ``None`` when the interval start is unknown."""

        if self.valid_from is None:
            return None if (self.valid_to is None or day < self.valid_to) else False
        if day < self.valid_from:
            return False
        return self.valid_to is None or day < self.valid_to


# --------------------------------------------------------------------------- evidence & sources


class SourceRef(_Model):
    """Provider identity and contract version for a collected artifact."""

    provider: str = Field(min_length=1)
    contract: str = Field(min_length=1)  # e.g. "korean-land-parcel-analysis/2"
    pinned_commit: str | None = None
    retrieved_at: datetime
    query: dict[str, Any] = Field(default_factory=dict)


class Evidence(_Model):
    """A located span of a snapshotted source. All facts, relations and findings cite these."""

    evidence_id: str = Field(min_length=1)
    source: SourceRef
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: dict[str, Any] = Field(default_factory=dict)  # page/article/paragraph/row/layer
    excerpt: str = ""
    public: bool = True  # False: project-private material, never shared across projects
    project_id: str | None = None

    @model_validator(mode="after")
    def _private_needs_project(self) -> Evidence:
        if not self.public and not self.project_id:
            raise ValueError("private evidence must name its project")
        return self


class CollectionResult(_Model):
    """One provider call. ``items`` are raw records; ``next_page`` set means more data exists."""

    node_id: str
    provider: str
    status: CollectionStatus
    items: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    error_kind: ErrorKind | None = None
    error: str | None = None
    retry_after_seconds: float | None = None
    next_page: str | None = None
    result_limit: int | None = None

    @model_validator(mode="after")
    def _consistent(self) -> CollectionResult:
        if self.status is CollectionStatus.FAILED and self.error_kind is None:
            raise ValueError("failed collections must carry an error_kind")
        if self.next_page and self.status is CollectionStatus.FOUND:
            raise ValueError("a result with a next page is truncated, not found")
        return self

    @property
    def complete(self) -> bool:
        """Only a FOUND or EMPTY result without further pages can support a negative check."""

        return (
            self.status in {CollectionStatus.FOUND, CollectionStatus.EMPTY} and not self.next_page
        )


# --------------------------------------------------------------------------- subjects


class ParcelPart(_Model):
    part_id: str
    pnu: str
    geometry_version: str | None = None
    area_m2: float | None = None
    precision: Literal["polygon", "point", "unknown"] = "unknown"


class Site(_Model):
    """Resolved site. ``candidates`` holds unresolved address matches (S01): never auto-pick."""

    address: str | None = None
    pnus: list[str] = Field(default_factory=list)
    parts: list[ParcelPart] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    jurisdiction_code: str | None = None  # 5-digit sigungu code when confirmed
    resolved: bool = False


class Proposal(_Model):
    project_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    actions: list[str] = Field(default_factory=list)  # e.g. "new_construction", "land_form_change"
    uses: list[str] = Field(default_factory=list)  # e.g. "warehouse"
    scale: dict[str, Any] = Field(default_factory=dict)  # gross_floor_area_m2, floors, height_m ...


class LegalEventDates(_Model):
    """Separate event dates; never collapsed into one ``as_of`` (section 7)."""

    review_date: date
    application_date: date | None = None
    permit_date: date | None = None
    action_date: date | None = None

    def governing_date(self) -> date:
        return self.application_date or self.permit_date or self.action_date or self.review_date


class ReviewScope(_Model):
    """Declared scope fixed at plan time; outputs claim coverage of this profile only."""

    profile_id: str = Field(min_length=1)  # e.g. "kr-landuse-building/2026.11"
    profile_version: str = Field(min_length=1)
    law_families: list[str] = Field(default_factory=list)  # nlupa, building_act, farmland ...
    excluded: list[str] = Field(default_factory=list)
    max_reference_depth: int = Field(default=4, ge=0, le=20)


# --------------------------------------------------------------------------- legal sources


class ProvisionRef(_Model):
    """Version-bound provision identity: law version + article/branch + paragraph/item/sub-item.

    ``kind`` distinguishes body articles from annexes (별표) and addenda (부칙), which have their
    own positions and are never merged with a same-numbered article.
    """

    work_id: str = Field(min_length=1)  # persistent law id (법령ID)
    version_id: str = Field(min_length=1)  # version id (MST)
    kind: Literal["article", "annex", "addendum"] = "article"
    article: int | None = Field(default=None, ge=1)
    branch: int | None = Field(default=None, ge=1)  # 가지번호: 제12조의2 -> article=12, branch=2
    paragraph: int | None = Field(default=None, ge=1)
    item: int | None = Field(default=None, ge=1)
    item_branch: int | None = Field(default=None, ge=1)  # 제1호의2 -> item=1, item_branch=2
    sub_item: str | None = None
    annex_no: str | None = None  # 별표 번호 ("1", "2의3")
    addendum_key: str | None = None  # 부칙 공포번호/일자 key

    @property
    def key(self) -> str:
        parts = [self.work_id, self.version_id, self.kind]
        for name in (
            "article",
            "branch",
            "paragraph",
            "item",
            "item_branch",
            "sub_item",
            "annex_no",
            "addendum_key",
        ):
            value = getattr(self, name)
            if value is not None:
                parts.append(f"{name}={value}")
        return "|".join(parts)


class LegalVersion(_Model):
    work_id: str
    version_id: str
    title: str
    promulgated_on: date | None = None
    effective: Interval
    jurisdiction_code: str | None = None  # None: national law
    authority: Literal["act", "decree", "rule", "ordinance", "notice", "plan"]
    snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Provision(_Model):
    ref: ProvisionRef
    title: str | None = None
    text: str
    evidence_id: str | None = None
    references: list[ProvisionRef] = Field(default_factory=list)
    reference_kinds: list[
        Literal["references", "delegates", "defines", "applies_mutatis", "excepts"]
    ] = Field(default_factory=list)


# --------------------------------------------------------------------------- facts


class Fact(_Model):
    """Bitemporal fact with provenance. ``value`` is ``None`` only for status UNKNOWN."""

    fact_id: str
    path: str = Field(min_length=1)  # rule fact path, e.g. "land.in_agricultural_promotion_area"
    subject: str  # parcel part / building / proposal id
    value: Any = None
    unit: str | None = None
    status: FactStatus
    method: Literal["official_record", "spatial_calc", "design_observed", "user_claim", "derived"]
    observation_scope: Literal["whole", "partial", "sample"] = "whole"
    validity: Interval = Field(default_factory=Interval)
    recorded_at: datetime
    superseded_at: datetime | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _status_value(self) -> Fact:
        if self.status is FactStatus.UNKNOWN and self.value is not None:
            raise ValueError("unknown facts carry no value")
        if self.status in {FactStatus.OBSERVED, FactStatus.CORROBORATED} and not self.evidence_ids:
            raise ValueError("observed/corroborated facts need evidence")
        return self


# --------------------------------------------------------------------------- findings


class CandidateProvision(_Model):
    candidate_id: str
    ref: ProvisionRef
    topic: str  # comparable unit: "use_permission", "coverage_ratio", "farmland_conversion" ...
    subject: str  # parcel part / building / action
    sources: list[CandidateSource]
    reasons: list[str] = Field(min_length=1)  # why discovered (never empty)
    required_facts: list[str] = Field(default_factory=list)
    exceptions_to_check: list[ProvisionRef] = Field(default_factory=list)
    required_references: list[ProvisionRef] = Field(default_factory=list)
    mandatory: bool = False  # part of the declared checklist: may never be silently dropped
    status: Applicability = Applicability.CANDIDATE


class ApplicabilityFinding(_Model):
    candidate_id: str
    status: Applicability
    reasons: list[str] = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    unresolved_exceptions: list[str] = Field(default_factory=list)
    review: InterpretationReview = InterpretationReview.UNREVIEWED

    @model_validator(mode="after")
    def _negative_needs_basis(self) -> ApplicabilityFinding:
        if self.status is Applicability.NOT_APPLICABLE and not (
            self.evidence_ids and self.fact_ids
        ):
            raise ValueError("not_applicable needs evidence and facts (no negative by absence)")
        return self


class RuleEvaluationRecord(_Model):
    rule_version_id: str
    candidate_id: str
    outcome: Outcome
    reason: str | None = None
    fact_ids: list[str] = Field(default_factory=list)
    input_digest: str
    reviewed: bool  # only reviewed (approved) rules may yield PASS/FAIL
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unreviewed_is_review(self) -> RuleEvaluationRecord:
        if not self.reviewed and self.outcome is not Outcome.REVIEW:
            raise ValueError("unreviewed rules can only yield REVIEW")
        return self


class Conflict(_Model):
    conflict_id: str
    topic: str
    subject: str
    candidate_ids: list[str] = Field(min_length=2)
    kind: Literal[
        "cumulative", "exception", "delegation", "special_rule", "transitional", "unresolved"
    ]
    basis_evidence_ids: list[str] = Field(default_factory=list)
    note: str


class UnresolvedItem(_Model):
    item_id: str
    kind: Literal[
        "missing_fact",
        "missing_document",
        "collection_failed",
        "truncated",
        "unsupported_source",
        "unresolved_reference",
        "unresolved_exception",
        "conflict",
        "site_ambiguous",
        "temporal_unresolved",
        "quarantined",
        "scope_expansion",
    ]
    subject: str | None = None
    detail: str
    blocking: bool = True
    task_id: str | None = None


class NextTask(_Model):
    task_id: str
    role: Literal["user", "data_operator", "rule_author", "legal_reviewer", "ops_admin"]
    reason: str
    target: str  # what to supply / check
    resolves: list[str] = Field(default_factory=list)  # UnresolvedItem ids


class CoverageItem(_Model):
    """One mandatory checklist row of the declared scope."""

    checklist_id: str
    label: str
    subject: str
    state: Literal["satisfied", "unresolved", "not_reached"]
    candidate_ids: list[str] = Field(default_factory=list)
    unresolved_ids: list[str] = Field(default_factory=list)


class Citation(_Model):
    claim: str
    evidence_ids: list[str] = Field(min_length=1)
    provision_key: str | None = None
    verified: bool = False
    failure: str | None = None


class ReviewSummary(_Model):
    """Section 14 summary; never an overall permission while a blocking item is unresolved."""

    has_confirmed_nonconformity: bool
    has_unresolved: bool
    scope_satisfied: bool
    remaining_procedures: list[str] = Field(default_factory=list)
    legacy_status: Literal[
        "permitted",
        "conditionally_permitted",
        "not_permitted",
        "insufficient_data",
        "conflict",
        "outside_scope",
    ]
    reason_codes: list[str] = Field(default_factory=list)
    advisory: bool = True
