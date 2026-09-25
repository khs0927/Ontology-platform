"""Additive database contract for evidence and relation verification state.

This revision is intentionally conservative: it adds missing nullable columns and
named checks, but never drops or rewrites existing data.  Existing installations
that already have the baseline columns are supported by the inspection guards.

Safety model for production upgrades
-------------------------------------
Every new constraint is preceded by a read-only preflight of the legacy rows.
The preflight never mutates data; when legacy rows would violate a constraint
that is about to be added, the migration aborts with an explicit, actionable
error instead of half-applying the revision.  Operators must either clean up
the reported rows or keep the deployment on the previous revision.

The evidence provenance foreign keys are additive and are only created when the
referencing column already exists and no equivalent constraint is present, so
databases created from ``migrations/001_core.sql`` and databases created from
``0001_baseline`` both converge to the same contract.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_evidence_contract"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_VERIFICATION_STATES = ("unverified", "machine_verified", "human_verified", "rejected")

_VERIFICATION_STATE_SQL = (
    "verification_state IN ('unverified', 'machine_verified', 'human_verified', 'rejected')"
)

# (table, constraint name, required columns, predicate that must hold for every
# legacy row).  ``required columns`` lets the preflight skip a constraint whose
# columns a legacy database does not have yet instead of failing on an unknown
# column; this revision itself is what adds the missing ones.  The excerpt-hash
# check is dialect specific and is appended by ``_constraint_specs`` so both
# dialects share a single preflight code path.
_CHECK_SPECS = (
    (
        "evidence",
        "ck_evidence_source",
        ("artifact_id", "chunk_id", "source_uri"),
        "artifact_id IS NOT NULL OR chunk_id IS NOT NULL OR source_uri IS NOT NULL",
    ),
    (
        "evidence",
        "ck_evidence_target_xor",
        ("entity_id", "relation_id"),
        "((entity_id IS NOT NULL AND relation_id IS NULL) OR "
        "(entity_id IS NULL AND relation_id IS NOT NULL))",
    ),
    (
        "evidence",
        "ck_evidence_verification_state",
        ("verification_state",),
        _VERIFICATION_STATE_SQL,
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
    (
        "relations",
        "ck_relation_verification_state",
        ("verification_state",),
        _VERIFICATION_STATE_SQL,
    ),
)

# (constraint name, local column, referenced table, referenced column).
_EVIDENCE_FOREIGN_KEYS = (
    ("fk_evidence_artifact_id", "artifact_id", "artifacts", "id"),
    ("fk_evidence_chunk_id", "chunk_id", "chunks", "id"),
)


def _add_missing_columns() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    evidence_columns = {column["name"] for column in inspector.get_columns("evidence")}
    for name, type_ in (
        ("artifact_id", sa.Uuid()),
        ("chunk_id", sa.Uuid()),
        ("source_uri", sa.Text()),
    ):
        if name not in evidence_columns:
            op.add_column("evidence", sa.Column(name, type_, nullable=True))

    relation_columns = {column["name"] for column in inspector.get_columns("relations")}
    if "verification_state" not in relation_columns:
        op.add_column(
            "relations",
            sa.Column("verification_state", sa.String(50), server_default="unverified", nullable=False),
        )


def _existing_check_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints(table)}


def _add_check(table: str, name: str, expression: str) -> None:
    if name in _existing_check_names(table):
        return
    with op.batch_alter_table(table) as batch:
        batch.create_check_constraint(name, expression)


def _hash_expression() -> str:
    # SQLite has GLOB, while PostgreSQL uses a POSIX regular expression.  Both
    # branches require the literal ``sha256:`` algorithm prefix.  The previous
    # PostgreSQL expression only constrained the 64 hex characters after
    # position 8, so it silently accepted any 7 character prefix (``md5:xxx``,
    # ``rot13:``) and made PostgreSQL disagree with SQLite on the same value.
    if op.get_bind().dialect.name == "postgresql":
        return (
            "excerpt_hash IS NULL OR (length(excerpt_hash) = 71 "
            "AND substring(excerpt_hash from 1 for 7) = 'sha256:' "
            "AND substring(excerpt_hash from 8) ~ '^[0-9a-f]{64}$')"
        )
    return "excerpt_hash IS NULL OR (length(excerpt_hash) = 71 AND substr(excerpt_hash, 1, 7) = 'sha256:' AND substr(excerpt_hash, 8) NOT GLOB '*[^0-9a-f]*')"


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def _column_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _constraint_specs() -> tuple[tuple[str, str, tuple[str, ...], str], ...]:
    return _CHECK_SPECS + (
        ("evidence", "ck_evidence_excerpt_hash", ("excerpt_hash",), _hash_expression()),
    )


def _count_violations(table: str, predicate: str) -> int:
    statement = sa.text(
        f"SELECT count(*) FROM {table} WHERE NOT ({predicate})"  # noqa: S608 - fixed identifiers
    )
    return int(op.get_bind().execute(statement).scalar() or 0)


def _preflight_checks() -> list[str]:
    """Report legacy rows that would break a constraint about to be added."""
    table_columns = {
        "evidence": _column_names("evidence"),
        "relations": _column_names("relations"),
    }
    findings: list[str] = []
    for table, name, required, predicate in _constraint_specs():
        if table not in table_columns:
            continue
        if not set(required) <= table_columns[table]:
            # A legacy database missing the column cannot violate the predicate;
            # the column itself is added by _add_missing_columns.
            continue
        violations = _count_violations(table, predicate)
        if violations:
            findings.append(
                f"{name}: {violations} legacy row(s) in {table} violate the new contract"
            )
    return findings


def _preflight_foreign_keys() -> list[str]:
    """Report orphaned evidence provenance references before adding FKs."""
    evidence_columns = _column_names("evidence")
    if not evidence_columns:
        return []

    findings: list[str] = []
    for name, column, referenced_table, referenced_column in _EVIDENCE_FOREIGN_KEYS:
        if column not in evidence_columns or not _column_names(referenced_table):
            continue
        if referenced_column not in _column_names(referenced_table):
            continue
        orphans = int(
            op.get_bind()
            .execute(
                sa.text(
                    f"SELECT count(*) FROM evidence e WHERE e.{column} IS NOT NULL "  # noqa: S608
                    f"AND NOT EXISTS (SELECT 1 FROM {referenced_table} r "  # noqa: S608
                    f"WHERE r.{referenced_column} = e.{column})"
                )
            )
            .scalar()
            or 0
        )
        if orphans:
            findings.append(
                f"{name}: {orphans} evidence row(s) reference a missing "
                f"{referenced_table}.{referenced_column} via {column}"
            )
    return findings


def preflight() -> list[str]:
    """Read-only inspection of legacy data for this revision.

    Returns the list of blocking findings; an empty list means the database can
    accept the new checks and foreign keys.
    """
    findings = _preflight_checks() + _preflight_foreign_keys()
    if findings:
        raise RuntimeError(
            "0002_evidence_contract preflight failed; no changes were applied. "
            "Resolve the legacy rows listed below and re-run the upgrade: "
            + "; ".join(findings)
        )
    return findings


def _existing_foreign_keys(table: str) -> set[tuple[str, str, str, str]]:
    existing: set[tuple[str, str, str, str]] = set()
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        referred = fk.get("referred_table") or ""
        referred_columns = list(fk.get("referred_columns") or [])
        for index, column in enumerate(fk.get("constrained_columns") or []):
            target = referred_columns[index] if index < len(referred_columns) else ""
            existing.add((column, referred, target, fk.get("name") or ""))
    return existing


def _add_evidence_foreign_keys() -> None:
    dialect = _dialect_name()
    evidence_columns = _column_names("evidence")
    if not evidence_columns:
        return

    existing = _existing_foreign_keys("evidence")
    existing_names = {name for *_, name in existing}
    for name, column, referenced_table, referenced_column in _EVIDENCE_FOREIGN_KEYS:
        if column not in evidence_columns or name in existing_names:
            continue
        if (column, referenced_table, referenced_column, "") in existing:
            continue
        if referenced_column not in _column_names(referenced_table):
            continue
        if dialect == "postgresql":
            op.create_foreign_key(
                name, "evidence", referenced_table, [column], [referenced_column]
            )
        elif dialect == "sqlite":
            with op.batch_alter_table("evidence") as batch:
                batch.create_foreign_key(name, referenced_table, [column], [referenced_column])
        else:
            raise RuntimeError(f"unsupported evidence-contract dialect: {dialect}")


def upgrade() -> None:
    _add_missing_columns()
    preflight()
    for table, name, _required, expression in _constraint_specs():
        _add_check(table, name, expression)
    _add_evidence_foreign_keys()


def downgrade() -> None:
    # Constraints and nullable evidence provenance are safe to retain; rolling
    # back must not destroy provenance or make a previously valid row invalid.
    raise NotImplementedError("Evidence contract is additive and is not destructively downgraded")
