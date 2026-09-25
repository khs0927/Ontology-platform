"""Add the PostgreSQL/pgvector embeddings contract.

This revision is additive on PostgreSQL.  The downgrade deliberately does not drop
objects: retaining embeddings and the extension is safer than making a rollback
silently destroy vector data.

Null ``content_hash`` uniqueness policy
--------------------------------------
``migrations/002_vector.sql`` enforces dedup with *partial* unique indexes that
ignore rows where ``content_hash IS NULL``.  The Alembic revision previously
emitted table-level ``UNIQUE`` constraints instead, which under PostgreSQL
default ``NULLS DISTINCT`` semantics never conflict on a NULL hash, so the
effect was the same but the enforcement depended on an implicit server setting.
``NULLS NOT DISTINCT`` (a per-table default in PostgreSQL 15+) would silently
turn those rows into conflicts and break legitimate re-embedding of unchanged
content.  This revision therefore emits explicit partial unique indexes with
``WHERE content_hash IS NOT NULL``, so the policy is independent of the
database's ``default_null_ordering``/``NULLS [NOT] DISTINCT`` configuration, and
keeps the named table-level constraints for databases that were already stamped.

DDL role and extension privileges
---------------------------------
``CREATE EXTENSION`` and ``ALTER TABLE ... ADD CONSTRAINT`` require elevated
privileges.  This revision assumes the role running Alembic may create the
``vector`` extension in the target database (typically the database owner or a
role granted ``CREATE`` on the database plus membership in the extension
owning role).  Operators should run the migration with a dedicated migration
role rather than the superuser; a missing privilege surfaces as a PostgreSQL
``insufficientPrivilege`` error naming the object, not as a silent downgrade.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """Minimal dependency-free pgvector type for Alembic DDL.

    SQLAlchemy 2.0 does not ship a PostgreSQL VECTOR type.  Keeping the DDL
    type local avoids adding a runtime dependency solely for migrations while
    still emitting the native pgvector column type.
    """

    cache_ok = True

    def get_col_spec(self, **_: object) -> str:
        return "VECTOR"

revision = "0003_vector_embeddings"
down_revision = "0002_evidence_contract"
branch_labels = None
depends_on = None

_EMBEDDING_DIMENSIONS = 1536

# Partial unique indexes mirroring migrations/002_vector.sql.  Rows without a
# content hash are intentionally excluded: an unknown hash cannot prove that two
# vectors describe the same content, so refusing the insert would be a false
# positive while allowing duplicates is recoverable by re-embedding.
_PARTIAL_UNIQUE_INDEXES = (
    (
        "uq_embeddings_entity_model_hash",
        ("entity_id", "model", "content_hash"),
        "entity_id IS NOT NULL AND content_hash IS NOT NULL",
    ),
    (
        "uq_embeddings_chunk_model_hash",
        ("chunk_id", "model", "content_hash"),
        "chunk_id IS NOT NULL AND content_hash IS NOT NULL",
    ),
)


def _postgres_only() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _existing_index_names() -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("embeddings")}


def _preflight_duplicate_embeddings() -> list[str]:
    """Report legacy duplicate (target, model, content_hash) rows.

    The partial unique indexes below cannot be created while duplicates exist.
    Failing here with counts is safer than dropping a duplicate row, because the
    operator decides which vector wins.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("embeddings"):
        return []

    columns = {column["name"] for column in inspector.get_columns("embeddings")}
    if not {"model", "content_hash"} <= columns:
        return []

    findings: list[str] = []
    for index_name, predicate, target_column in (
        ("uq_embeddings_entity_model_hash", "entity_id IS NOT NULL", "entity_id"),
        ("uq_embeddings_chunk_model_hash", "chunk_id IS NOT NULL", "chunk_id"),
    ):
        if target_column not in columns:
            continue
        duplicates = int(
            bind.execute(
                sa.text(
                    "SELECT count(*) FROM ("
                    f"SELECT {target_column}, model, content_hash FROM embeddings "  # noqa: S608
                    f"WHERE {predicate} AND content_hash IS NOT NULL "  # noqa: S608
                    "GROUP BY 1, 2, 3 HAVING count(*) > 1) duplicates"
                )
            ).scalar()
            or 0
        )
        if duplicates:
            findings.append(
                f"{index_name}: {duplicates} duplicate ({target_column}, model, "
                "content_hash) group(s) exist"
            )
    return findings


def preflight() -> list[str]:
    """Read-only inspection of legacy data for this revision."""
    findings = _preflight_duplicate_embeddings()
    if findings:
        raise RuntimeError(
            "0003_vector_embeddings preflight failed; no changes were applied. "
            "De-duplicate the rows listed below and re-run the upgrade: "
            + "; ".join(findings)
        )
    return findings


def _create_partial_unique_indexes() -> None:
    existing = _existing_index_names()
    for name, columns, predicate in _PARTIAL_UNIQUE_INDEXES:
        if name in existing:
            continue
        op.create_index(
            name,
            "embeddings",
            list(columns),
            unique=True,
            postgresql_where=sa.text(predicate),
        )


def upgrade() -> None:
    if not _postgres_only():
        raise RuntimeError("0003_vector_embeddings requires PostgreSQL with pgvector")

    if sa.inspect(op.get_bind()).has_table("embeddings"):
        # Already provisioned from migrations/002_vector.sql: keep the data and
        # only converge on the named contract.
        preflight()
        _create_partial_unique_indexes()
        return

    preflight()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("entities.id", ondelete="CASCADE")),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chunks.id", ondelete="CASCADE")),
        sa.Column("model", sa.String(300), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("content_hash", sa.String(200)),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()),
                  server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("dimensions > 0", name="ck_embeddings_dimensions_positive"),
        sa.CheckConstraint("vector_dims(embedding) = dimensions", name="ck_embeddings_shape"),
        sa.CheckConstraint(
            "(entity_id IS NOT NULL AND chunk_id IS NULL) OR "
            "(entity_id IS NULL AND chunk_id IS NOT NULL)",
            name="ck_embeddings_target_xor",
        ),
        sa.UniqueConstraint(
            "entity_id", "model", "content_hash", name="uq_embeddings_entity_model_content"
        ),
        sa.UniqueConstraint(
            "chunk_id", "model", "content_hash", name="uq_embeddings_chunk_model_content"
        ),
    )
    op.create_index("idx_embeddings_model_dimensions", "embeddings", ["model", "dimensions"])
    op.create_index("idx_embeddings_entity", "embeddings", ["entity_id"])
    op.create_index("idx_embeddings_chunk", "embeddings", ["chunk_id"])
    _create_partial_unique_indexes()


def downgrade() -> None:
    # Deliberate no-op: dropping the table or extension would destroy vector data.
    return None
