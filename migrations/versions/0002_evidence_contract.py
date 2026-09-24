"""Additive database contract for evidence and relation verification state.

This revision is intentionally conservative: it adds missing nullable columns and
named checks, but never drops or rewrites existing data.  Existing installations
that already have the baseline columns are supported by the inspection guards.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_evidence_contract"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_VERIFICATION_STATES = ("unverified", "machine_verified", "human_verified", "rejected")


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
    # SQLite has GLOB, while PostgreSQL uses a POSIX regular expression.
    if op.get_bind().dialect.name == "postgresql":
        return "excerpt_hash IS NULL OR (length(excerpt_hash) = 71 AND substring(excerpt_hash from 8) ~ '^[0-9a-f]{64}$')"
    return "excerpt_hash IS NULL OR (length(excerpt_hash) = 71 AND substr(excerpt_hash, 1, 7) = 'sha256:' AND substr(excerpt_hash, 8) NOT GLOB '*[^0-9a-f]*')"


def upgrade() -> None:
    _add_missing_columns()
    _add_check("evidence", "ck_evidence_source", "artifact_id IS NOT NULL OR chunk_id IS NOT NULL OR source_uri IS NOT NULL")
    _add_check("evidence", "ck_evidence_target_xor", "((entity_id IS NOT NULL AND relation_id IS NULL) OR (entity_id IS NULL AND relation_id IS NOT NULL))")
    _add_check("evidence", "ck_evidence_excerpt_hash", _hash_expression())
    _add_check("evidence", "ck_evidence_verification_state", "verification_state IN ('unverified', 'machine_verified', 'human_verified', 'rejected')")
    _add_check("relations", "ck_relation_no_self_loop", "source_entity_id <> target_entity_id")
    _add_check("relations", "ck_relation_temporal_order", "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from")
    _add_check("relations", "ck_relation_verification_state", "verification_state IN ('unverified', 'machine_verified', 'human_verified', 'rejected')")


def downgrade() -> None:
    # Constraints and nullable evidence provenance are safe to retain; rolling
    # back must not destroy provenance or make a previously valid row invalid.
    raise NotImplementedError("Evidence contract is additive and is not destructively downgraded")
