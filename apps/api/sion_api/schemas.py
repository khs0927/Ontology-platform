from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Mirrors the verification_state CHECK constraints in migrations/001_core.sql.
VerificationState = Literal["unverified", "machine_verified", "human_verified", "rejected"]


class EntityCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=500)
    entity_type_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    category: str | None = None
    external_uri: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    ontology_version: str | None = None


class EntityRead(EntityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class RelationCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=700)
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relation_type_id: str = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_state: VerificationState = "unverified"
    source_kind: str | None = None
    ontology_version: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("valid_from", "valid_to", mode="before")
    @classmethod
    def normalize_relation_time(cls, value):
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value

    @model_validator(mode="after")
    def no_typed_self_loop(self):
        # Mirrors the relations self-loop CHECK in migrations/001_core.sql.
        if self.source_entity_id == self.target_entity_id and self.relation_type_id != "RELATED_TO":
            raise ValueError("self-referencing relations must use RELATED_TO")
        return self

    @model_validator(mode="after")
    def validity_order(self):
        if self.valid_from and self.valid_to:
            left = self.valid_from
            right = self.valid_to
            if left.tzinfo is None:
                left = left.replace(tzinfo=timezone.utc)
            if right.tzinfo is None:
                right = right.replace(tzinfo=timezone.utc)
            if right < left:
                raise ValueError("valid_to must not precede valid_from")
        return self


class RelationRead(RelationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class RelationInvalidate(BaseModel):
    valid_to: datetime
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def timezone_required(self):
        if self.valid_to.tzinfo is None or self.valid_to.utcoffset() is None:
            raise ValueError("valid_to must include a timezone")
        self.valid_to = self.valid_to.astimezone(timezone.utc)
        return self


class EvidenceCreate(BaseModel):
    entity_id: uuid.UUID | None = None
    relation_id: uuid.UUID | None = None
    source_uri: str = Field(min_length=1)
    source_locator: str | None = None
    excerpt_hash: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_state: VerificationState = "unverified"
    extractor: str | None = None
    model: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_target(self):
        if self.entity_id is None and self.relation_id is None:
            raise ValueError("entity_id or relation_id is required")
        return self


class EvidenceRead(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class GraphEdge(BaseModel):
    id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID
    type: str
    confidence: float | None = None
    verification_state: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @field_validator("valid_from", "valid_to", mode="before")
    @classmethod
    def normalize_graph_time(cls, value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value


class GraphResponse(BaseModel):
    nodes: list[EntityRead]
    edges: list[GraphEdge]
    node_count: int
    edge_count: int


class EmbeddingCreate(BaseModel):
    entity_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    model: str = Field(min_length=1, max_length=300)
    embedding: list[float] = Field(min_length=1, max_length=8192)
    content_hash: str | None = Field(default=None, max_length=200)
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_target(self):
        if (self.entity_id is None) == (self.chunk_id is None):
            raise ValueError("exactly one of entity_id or chunk_id is required")
        return self


class EmbeddingRead(BaseModel):
    id: uuid.UUID
    entity_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    model: str
    dimensions: int
    content_hash: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class VectorSearchRequest(BaseModel):
    model: str = Field(min_length=1, max_length=300)
    embedding: list[float] = Field(min_length=1, max_length=8192)
    limit: int = Field(default=10, ge=1, le=100)
    target_kind: str | None = Field(default=None, pattern="^(entity|chunk)$")


class VectorHit(BaseModel):
    id: uuid.UUID
    entity_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    model: str
    dimensions: int
    similarity: float
    content_hash: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class VectorSearchResponse(BaseModel):
    hits: list[VectorHit]
    count: int


class ArtifactCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    storage_uri: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, max_length=200)
    mime_type: str | None = Field(default=None, max_length=300)
    byte_size: int | None = Field(default=None, ge=0)
    provider: str | None = Field(default=None, max_length=100)
    provider_file_id: str | None = Field(default=None, max_length=500)
    properties: dict[str, Any] = Field(default_factory=dict)


class ArtifactRead(ArtifactCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class GraphRagQuery(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["local", "global", "hybrid", "naive", "mix"] = "mix"
    top_k: int = Field(default=20, ge=1, le=200)
    # Query one project's own LightRAG workspace. Required for project-restricted callers.
    project_id: uuid.UUID | None = None


class OutboxEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    attempts: int
    last_error: str | None = None
    next_attempt_at: datetime | None = None


class OutboxFailure(BaseModel):
    id: uuid.UUID
    error: str = Field(min_length=1, max_length=2000)


class OutboxAck(BaseModel):
    published: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    failed: list[OutboxFailure] = Field(default_factory=list, max_length=1000)
    consumer: str | None = Field(default=None, max_length=200)


class RegulationEvaluate(BaseModel):
    rule: dict[str, Any]
    facts: dict[str, Any] = Field(default_factory=dict)
    entity_id: uuid.UUID | None = None
    # korean-land-mcp analyze_parcel record (contract korean-land-parcel-analysis/2) -> land.* facts
    land_parcel: dict[str, Any] | None = None


class CandidateDecision(BaseModel):
    """Approve/reject one pending candidate.

    An approval records a reviewer's judgement of a candidate (``human_verified``); it does not
    verify the underlying fact and never overwrites confidence or evidence. It casts one
    reversible vote on that candidate's extraction rule or guideline predicate, which can
    change only the ranking score of later candidates. It never auto-verifies them.
    """

    reviewer: str | None = Field(default=None, max_length=200, description="Recorded in properties.review.reviewer")
    note: str | None = Field(default=None, max_length=2000, description="Recorded in properties.review.note")
    # Optimistic concurrency: the candidate ``version`` the reviewer saw (409 with the current one on
    # mismatch). Optional unless SION_REVIEW_REQUIRE_VERSION is on.
    expected_version: int | None = Field(default=None, ge=0)
    # Return the exact would-be result without writing anything.
    dry_run: bool = False
    # Explicit human confirmation for approving a low-trust inferred edge.
    confirm_low_trust: bool = False


class BulkCandidateDecision(BaseModel):
    """One human decision for an explicit list of candidate ids (no filters, no auto-selection).

    An approval is a review judgement, not a fact verification. Each applied item records the
    shared ``batch_id``; the per-id results are also kept in a ``review.batch_decided`` outbox event.
    """

    # Each id is bounded (a UUID is 36 chars) because the per-id results, including ``invalid_id``
    # entries, are persisted in the ``review.batch_decided`` outbox payload.
    ids: list[Annotated[str, Field(max_length=64)]] = Field(
        min_length=1, max_length=1000, description="Candidate relation ids the reviewer selected (each at most 64 chars)"
    )
    decision: Literal["approve", "reject"] = Field(
        description="approve -> human_verified (review judgement, not fact verification); reject -> rejected (row kept)"
    )
    note: str = Field(min_length=1, max_length=2000, description="Required; recorded on every applied item")
    reviewer: str | None = Field(default=None, max_length=200)
    # id -> version the reviewer saw; a mismatch is a per-item ``conflict`` carrying the current version.
    expected_versions: dict[str, int] | None = None
    dry_run: bool = False
    confirm_low_trust: bool = False

    @field_validator("note")
    @classmethod
    def _note_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("note is required for bulk decisions")
        return value


class CandidateReopen(BaseModel):
    """Undo a mistaken approve/reject or re-review a candidate: it returns to pending and the old
    decision (reviewer, note, batch_id) is kept in ``properties.review_history``. The opposite
    decision can only be recorded after a reopen. Reopening also removes that candidate's
    extraction-weight vote, so later ranking no longer includes it."""

    note: str = Field(min_length=1, max_length=2000, description="Required reason for re-review")
    reviewer: str | None = Field(default=None, max_length=200)
    expected_version: int | None = Field(default=None, ge=0)
    dry_run: bool = False

    @field_validator("note")
    @classmethod
    def _note_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("note is required to reopen a decision")
        return value


class RelationExtractionRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=500)
    min_cooccurrence: int = Field(default=2, ge=1, le=100)
    include_cooccurrence: bool = True


class LlmExtractionRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)


class IngestJobRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=1000)
    extract_relations: bool = True


class GraphExportImportRequest(BaseModel):
    path: str = Field(min_length=1)
    namespace: str | None = Field(default=None, max_length=120, pattern=r"^[0-9A-Za-z._-]+$")
    expected_node_count: int | None = Field(default=None, ge=0)
    expected_edge_count: int | None = Field(default=None, ge=0)
    as_candidates: bool = True
    graph_index: int | None = Field(default=None, ge=0)
    allow_implicit_nodes: bool = False
    dry_run: bool = False


class LightRagExtractionRequest(BaseModel):
    max_nodes: int = Field(default=1000, ge=1, le=20000)
