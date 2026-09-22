from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VerificationState = Literal["unverified", "machine_verified", "human_verified", "rejected"]


class EntityCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    properties: dict[str, Any] | None = None


class EntityRead(EntityCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime


class RelationCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=255)
    source_entity_id: str
    target_entity_id: str
    relation_type: str = Field(min_length=1, max_length=120)
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_state: VerificationState = "unverified"
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationRead(RelationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class EvidenceCreate(BaseModel):
    entity_id: str | None = None
    relation_id: str | None = None
    source_uri: str | None = None
    source_locator: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_state: VerificationState = "unverified"
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_target(self):
        if not self.entity_id and not self.relation_id:
            raise ValueError("entity_id or relation_id is required")
        return self


class EvidenceRead(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
