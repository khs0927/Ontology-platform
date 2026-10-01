from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    verification_state: str = "unverified"
    source_kind: str | None = None
    ontology_version: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validity_order(self):
        if self.valid_from and self.valid_to:
            left = self.valid_from
            right = self.valid_to
            if left.tzinfo is None:
                left = left.replace(tzinfo=timezone.utc)
            if right.tzinfo is None:
                right = right.replace(tzinfo=__import__("datetime").timezone.utc)
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
        return self


class EvidenceCreate(BaseModel):
    entity_id: uuid.UUID | None = None
    relation_id: uuid.UUID | None = None
    source_uri: str = Field(min_length=1)
    source_locator: str | None = None
    excerpt_hash: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_state: str = "unverified"
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
