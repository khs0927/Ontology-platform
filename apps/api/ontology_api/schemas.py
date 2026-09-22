from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

VerificationState = Literal["unverified", "machine_verified", "human_verified", "rejected"]


class EntityCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=255)
    entity_type_id: str = Field(min_length=1, max_length=120, validation_alias=AliasChoices("entity_type_id", "entity_type"))
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    external_uri: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    ontology_version: str | None = None


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    external_uri: str | None = None
    properties: dict[str, Any] | None = None
    ontology_version: str | None = None


class EntityRead(EntityCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime


class RelationCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=255)
    source_entity_id: str
    target_entity_id: str
    relation_type_id: str = Field(min_length=1, max_length=120, validation_alias=AliasChoices("relation_type_id", "relation_type"))
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_state: VerificationState = "unverified"
    source_kind: str | None = None
    ontology_version: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationRead(RelationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class ArtifactCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    storage_uri: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    mime_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    provider: str | None = None
    provider_file_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ArtifactRead(ArtifactCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class EvidenceCreate(BaseModel):
    entity_id: str | None = None
    relation_id: str | None = None
    artifact_id: str | None = None
    chunk_id: str | None = None
    source_uri: str | None = None
    source_locator: str | None = None
    excerpt_hash: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_state: VerificationState = "unverified"
    extractor: str | None = None
    model: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence(self):
        if not self.entity_id and not self.relation_id:
            raise ValueError("entity_id or relation_id is required")
        if not self.artifact_id and not self.chunk_id and not self.source_uri:
            raise ValueError("artifact_id, chunk_id or source_uri is required")
        return self


class EvidenceRead(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
