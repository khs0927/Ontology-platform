"""Align legacy column capacities and checks with the canonical ORM.

Only capacity-widening changes and named checks are applied.  Existing columns
and data are retained, and downgrade is deliberately a no-op.
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_schema_parity"
down_revision = "0003_vector_embeddings"
branch_labels = None
depends_on = None


# (table, column, legacy VARCHAR capacity, canonical target).  Text targets are
# represented as None.  Narrowing changes are intentionally excluded.
_CAPACITY_PARITY = (
    ("artifacts", "provider_file_id", 200, 500),
    ("documents", "language", 20, 50),
    ("documents", "title", 500, None),
    ("relations", "stable_key", 500, 700),
    ("relations", "verification_state", 30, 50),
)

_CHECK_PARITY = (
    ("artifacts", "ck_artifact_byte_size", "byte_size IS NULL OR byte_size >= 0"),
    (
        "chunks",
        "ck_chunk_ordinal",
        "ordinal >= 0",
    ),
    (
        "relations",
        "ck_relation_confidence",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    ),
)


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def _column(table: str, name: str) -> dict | None:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return next((column for column in columns if column["name"] == name), None)


def _widen_column(table: str, name: str, legacy_length: int, target_length: int | None) -> None:
    column = _column(table, name)
    if column is None:
        return

    current_length = getattr(column.get("type"), "length", None)
    if target_length is not None and current_length is not None and current_length >= target_length:
        return
    if target_length is None and isinstance(column.get("type"), sa.Text):
        return

    target_type = sa.Text() if target_length is None else sa.String(target_length)
    if _dialect_name() == "postgresql":
        op.alter_column(
            table,
            name,
            existing_type=sa.String(legacy_length),
            type_=target_type,
            existing_nullable=column.get("nullable", True),
        )
        return

    if _dialect_name() == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                name,
                existing_type=sa.String(legacy_length),
                type_=target_type,
                existing_nullable=column.get("nullable", True),
            )
        return

    raise RuntimeError(f"unsupported schema-parity dialect: {_dialect_name()}")


def _add_check(table: str, name: str, expression: str) -> None:
    existing = {
        item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints(table)
    }
    if name in existing:
        return

    if _dialect_name() == "postgresql":
        op.create_check_constraint(name, table, expression)
    elif _dialect_name() == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(name, expression)
    else:
        raise RuntimeError(f"unsupported schema-parity dialect: {_dialect_name()}")


def upgrade() -> None:
    for table, column, legacy_length, target_length in _CAPACITY_PARITY:
        _widen_column(table, column, legacy_length, target_length)
    for table, name, expression in _CHECK_PARITY:
        _add_check(table, name, expression)


def downgrade() -> None:
    # Retain widened columns and checks: reversing them could reject data that
    # was valid under the canonical ORM.
    return None
