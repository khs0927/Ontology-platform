from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OntologyVersion(Base):
    __tablename__ = "ontology_versions"

    version: Mapped[str] = mapped_column(Text, primary_key=True)
    schema_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class EntityType(Base):
    __tablename__ = "entity_types"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    parent_type_id: Mapped[str | None] = mapped_column(ForeignKey("entity_types.id"), nullable=True)
    schema_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)


class RelationType(Base):
    __tablename__ = "relation_types"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    inverse_type_id: Mapped[str | None] = mapped_column(ForeignKey("relation_types.id"), nullable=True)
    source_type_id: Mapped[str | None] = mapped_column(ForeignKey("entity_types.id"), nullable=True)
    target_type_id: Mapped[str | None] = mapped_column(ForeignKey("entity_types.id"), nullable=True)
    transitive: Mapped[bool] = mapped_column(Boolean, default=False)
    is_symmetric: Mapped[bool] = mapped_column(Boolean, default=False)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint(
            "category IS NULL OR category IN ('core','architecture_site','cad_bim','ai_automation','content_assets','data_validation')",
            name="ck_entities_category",
        ),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    stable_key: Mapped[str] = mapped_column(Text, unique=True, index=True)
    entity_type_id: Mapped[str] = mapped_column(ForeignKey("entity_types.id"), index=True)
    name: Mapped[str] = mapped_column(Text, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    external_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    ontology_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_artifact_byte_size"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    entity_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), unique=True, nullable=True, index=True)
    stable_key: Mapped[str] = mapped_column(Text, unique=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    provider_file_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    entity_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), unique=True, nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_chunk_ordinal"),
        UniqueConstraint("document_id", "ordinal", name="uq_chunk_document_ordinal"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)


class Relation(Base):
    __tablename__ = "relations"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_relation_confidence"),
        CheckConstraint(
            "verification_state IN ('unverified','machine_verified','human_verified','rejected')",
            name="ck_relation_verification_state",
        ),
        CheckConstraint(
            "source_entity_id <> target_entity_id OR relation_type_id = 'RELATED_TO'",
            name="ck_relation_self_loop",
        ),
        CheckConstraint(
            "source_kind IS NULL OR source_kind IN ('user','document','file','database','api','mcp','inferred','imported')",
            name="ck_relations_source_kind",
        ),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    stable_key: Mapped[str] = mapped_column(Text, unique=True, index=True)
    source_entity_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    target_entity_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    relation_type_id: Mapped[str] = mapped_column(ForeignKey("relation_types.id"), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_state: Mapped[str] = mapped_column(Text, default="unverified")
    source_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    ontology_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint("entity_id IS NOT NULL OR relation_id IS NOT NULL", name="ck_evidence_target"),
        CheckConstraint("artifact_id IS NOT NULL OR chunk_id IS NOT NULL OR source_uri IS NOT NULL", name="ck_evidence_source"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_evidence_confidence"),
        CheckConstraint(
            "verification_state IN ('unverified','machine_verified','human_verified','rejected')",
            name="ck_evidence_verification_state",
        ),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_uuid)
    entity_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("entities.id", ondelete="CASCADE"), nullable=True, index=True)
    relation_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("relations.id", ondelete="CASCADE"), nullable=True, index=True)
    artifact_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=True)
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_state: Mapped[str] = mapped_column(Text, default="unverified")
    extractor: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
