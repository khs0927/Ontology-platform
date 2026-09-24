"""Baseline for the existing PostgreSQL schema.

Production databases are introduced with ``alembic stamp 0001_baseline`` after
provisioning.  Fresh PostgreSQL databases may opt into bootstrap creation with
``SION_ALEMBIC_EXECUTE_SCHEMA_CREATE=1 alembic upgrade head``; existing
databases must use stamp, never a second schema creation run.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _execute_schema_create() -> bool:
    import os
    return os.getenv("SION_ALEMBIC_EXECUTE_SCHEMA_CREATE", "0") == "1"


def _schema() -> None:
    op.create_table(
        "ontology_versions",
        sa.Column("version", sa.String(100), primary_key=True),
        sa.Column("schema_hash", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text()),
    )
    op.create_table(
        "entity_types",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("parent_type_id", sa.String(100), sa.ForeignKey("entity_types.id")),
        sa.Column("schema_uri", sa.Text()),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.create_table(
        "relation_types",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("inverse_type_id", sa.String(100), sa.ForeignKey("relation_types.id")),
        sa.Column("source_type_id", sa.String(100), sa.ForeignKey("entity_types.id")),
        sa.Column("target_type_id", sa.String(100), sa.ForeignKey("entity_types.id")),
        sa.Column("transitive", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_symmetric", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("stable_key", sa.String(500), nullable=False, unique=True),
        sa.Column("entity_type_id", sa.String(100), sa.ForeignKey("entity_types.id"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False), sa.Column("description", sa.Text()),
        sa.Column("category", sa.String(100)), sa.Column("external_uri", sa.Text()),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("ontology_version", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("stable_key", sa.String(500), nullable=False, unique=True), sa.Column("name", sa.String(500), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False), sa.Column("content_hash", sa.String(200)),
        sa.Column("mime_type", sa.String(300)), sa.Column("byte_size", sa.BigInteger()),
        sa.Column("provider", sa.String(100)), sa.Column("provider_file_id", sa.String(200)),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), unique=True),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("artifacts.id")), sa.Column("language", sa.String(20)),
        sa.Column("title", sa.String(500)), sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(200)), sa.Column("locator", sa.Text()),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.UniqueConstraint("document_id", "ordinal"),
    )
    op.create_table(
        "relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("stable_key", sa.String(500), nullable=False, unique=True),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type_id", sa.String(100), sa.ForeignKey("relation_types.id"), nullable=False),
        sa.Column("confidence", sa.Float()), sa.Column("verification_state", sa.String(30), server_default="unverified", nullable=False),
        sa.Column("source_kind", sa.String(100)), sa.Column("ontology_version", sa.String(100)),
        sa.Column("valid_from", sa.DateTime(timezone=True)), sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE")),
        sa.Column("relation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("relations.id", ondelete="CASCADE")),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("artifacts.id")),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chunks.id")), sa.Column("source_uri", sa.Text()),
        sa.Column("source_locator", sa.Text()), sa.Column("excerpt_hash", sa.String(200)), sa.Column("confidence", sa.Float()),
        sa.Column("verification_state", sa.String(30), server_default="unverified", nullable=False), sa.Column("extractor", sa.String(200)),
        sa.Column("model", sa.String(200)), sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_entities_type", "entities", ["entity_type_id"])
    op.create_index("idx_entities_category", "entities", ["category"])
    op.create_index("idx_relations_source", "relations", ["source_entity_id"])
    op.create_index("idx_relations_target", "relations", ["target_entity_id"])
    op.create_index("idx_relations_type", "relations", ["relation_type_id"])
    op.create_index("idx_evidence_relation", "evidence", ["relation_id"])
    op.create_index("idx_evidence_entity", "evidence", ["entity_id"])
    op.create_index("idx_chunks_document", "chunks", ["document_id"])


def baseline_stamp() -> None:
    """Operational marker for databases provisioned from the legacy SQL."""
    return None


def upgrade() -> None:
    if _execute_schema_create():
        _schema()


def downgrade() -> None:
    raise NotImplementedError("Baseline schema is not destructively downgraded")
