"""Align legacy column capacities and checks with the canonical ORM.

Only capacity-widening changes and named checks are applied.  Existing columns
and data are retained, and downgrade is deliberately a no-op.

Safety model for production upgrades
-------------------------------------
Every widening and every named check is preceded by a read-only ``preflight``.
Without it, a legacy row that violates a check this revision is about to add is
only discovered *after* the earlier widenings have been committed: the revision
then aborts with a raw ``IntegrityError`` and leaves the database partially
migrated.  The preflight inspects the legacy rows first and aborts the whole
revision with an actionable ``RuntimeError`` before any DDL is emitted.

The preflight also reports orphaned foreign-key references, because the SQLite
path widens columns with ``batch_alter_table``, which rebuilds the table under
foreign-key enforcement; an orphan that is invisible to the checks would still
abort the rebuild halfway.

The preflight never mutates data.  Operators must either clean up the reported
rows or keep the deployment on the previous revision.
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

# (table, constraint name, required columns, predicate that must hold for every
# legacy row).  ``required columns`` lets the preflight skip a table/column pair
# a legacy database does not have yet, mirroring the 0002 preflight, so the same
# code path serves databases created from migrations/001_core.sql and from
# 0001_baseline.  The two checks this revision does not create
# (``ck_relation_no_self_loop`` and ``ck_relation_temporal_order``) are included
# because the SQLite batch rebuild re-asserts them.
_PREFLIGHT_CHECKS = (
    ("artifacts", "ck_artifact_byte_size", ("byte_size",), "byte_size IS NULL OR byte_size >= 0"),
    ("chunks", "ck_chunk_ordinal", ("ordinal",), "ordinal >= 0"),
    (
        "relations",
        "ck_relation_confidence",
        ("confidence",),
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    ),
    (
        "relations",
        "ck_relation_no_self_loop",
        ("source_entity_id", "target_entity_id"),
        "source_entity_id <> target_entity_id",
    ),
    (
        "relations",
        "ck_relation_temporal_order",
        ("valid_from", "valid_to"),
        "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
    ),
)

# (constraint name, child table, child column, parent table, parent column).
_PREFLIGHT_FOREIGN_KEYS = (
    ("fk_documents_entity_id", "documents", "entity_id", "entities", "id"),
    ("fk_documents_artifact_id", "documents", "artifact_id", "artifacts", "id"),
    ("fk_chunks_document_id", "chunks", "document_id", "documents", "id"),
    ("fk_relations_source_entity_id", "relations", "source_entity_id", "entities", "id"),
    ("fk_relations_target_entity_id", "relations", "target_entity_id", "entities", "id"),
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


def _column_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _count_violations(table: str, predicate: str) -> int:
    statement = sa.text(
        f"SELECT count(*) FROM {table} WHERE NOT ({predicate})"  # noqa: S608 - fixed identifiers
    )
    return int(op.get_bind().execute(statement).scalar() or 0)


def _preflight_checks() -> list[str]:
    """Report legacy rows that would break a check about to be added."""
    table_columns = {
        table: _column_names(table)
        for table in sorted({spec[0] for spec in _PREFLIGHT_CHECKS})
    }
    findings: list[str] = []
    for table, name, required, predicate in _PREFLIGHT_CHECKS:
        columns = table_columns[table]
        if not columns or not set(required) <= columns:
            # A missing table or column cannot violate the predicate: an absent
            # column is simply not widened, and the table is left untouched.
            continue
        violations = _count_violations(table, predicate)
        if violations:
            findings.append(
                f"{name}: {violations} legacy row(s) in {table} violate the new contract"
            )
    return findings


def _preflight_foreign_keys() -> list[str]:
    """Report orphaned references before the batch rebuild re-asserts the FKs."""
    table_columns: dict[str, set[str]] = {}
    for table in sorted({spec[1] for spec in _PREFLIGHT_FOREIGN_KEYS}):
        table_columns[table] = _column_names(table)
    parent_columns: dict[str, set[str]] = {}
    for table in sorted({spec[3] for spec in _PREFLIGHT_FOREIGN_KEYS}):
        parent_columns[table] = _column_names(table)

    findings: list[str] = []
    for name, table, column, parent_table, parent_column in _PREFLIGHT_FOREIGN_KEYS:
        if column not in table_columns.get(table, set()):
            continue
        if parent_column not in parent_columns.get(parent_table, set()):
            continue
        orphans = int(
            op.get_bind()
            .execute(
                sa.text(
                    f"SELECT count(*) FROM {table} c WHERE c.{column} IS NOT NULL "  # noqa: S608
                    f"AND NOT EXISTS (SELECT 1 FROM {parent_table} p "  # noqa: S608
                    f"WHERE p.{parent_column} = c.{column})"
                )
            )
            .scalar()
            or 0
        )
        if orphans:
            findings.append(
                f"{name}: {orphans} {table} row(s) reference a missing "
                f"{parent_table}.{parent_column} via {column}"
            )
    return findings


def preflight() -> list[str]:
    """Read-only inspection of legacy data for this revision.

    Returns the list of blocking findings; an empty list means the database can
    accept the widenings and the named checks.
    """
    findings = _preflight_checks() + _preflight_foreign_keys()
    if findings:
        raise RuntimeError(
            "0004_schema_parity preflight failed; no changes were applied. "
            "Resolve the legacy rows listed below and re-run the upgrade: "
            + "; ".join(findings)
        )
    return findings


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
    # Refuse before any DDL: a legacy violation discovered halfway through would
    # leave the database partially migrated.
    preflight()
    for table, column, legacy_length, target_length in _CAPACITY_PARITY:
        _widen_column(table, column, legacy_length, target_length)
    for table, name, expression in _CHECK_PARITY:
        _add_check(table, name, expression)


def downgrade() -> None:
    # Retain widened columns and checks: reversing them could reject data that
    # was valid under the canonical ORM.
    return None
