"""Add the PostgreSQL/pgvector embeddings contract.

This revision is additive on PostgreSQL.  The downgrade deliberately does not drop
objects: retaining embeddings and the extension is safer than making a rollback
silently destroy vector data.
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


def _postgres_only() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _postgres_only():
        raise RuntimeError("0003_vector_embeddings requires PostgreSQL with pgvector")

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


def downgrade() -> None:
    # Deliberate no-op: dropping the table or extension would destroy vector data.
    return None
