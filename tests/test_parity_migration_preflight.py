"""Focused tests for the ``0004_schema_parity`` read-only preflight.

The parity revision widens legacy columns and adds named checks.  Without a
preflight, a legacy row that violates one of those checks is discovered only
after the earlier widenings have been committed, so the revision aborts halfway
and leaves the database partially migrated.  These tests pin the preflight:
every check violation and every orphaned reference must abort the revision
*before* any widening is applied, and a conforming legacy database must still
upgrade cleanly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).parents[1]
PARITY_MIGRATION = ROOT / "migrations/versions/0004_schema_parity.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PARITY_MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_connection():
    """A pre-0004 database shaped like the legacy SQL migrations.

    Capacity-repair targets are still at their legacy widths, and the canonical
    check columns are present but unconstrained.
    """
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text(
            "CREATE TABLE entities (id VARCHAR PRIMARY KEY, stable_key VARCHAR(700))"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE artifacts (id VARCHAR PRIMARY KEY, name VARCHAR(200), "
            "provider_file_id VARCHAR(200), byte_size BIGINT, content_hash VARCHAR(200))"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE documents (id VARCHAR PRIMARY KEY, entity_id VARCHAR, "
            "artifact_id VARCHAR, language VARCHAR(20), title VARCHAR(500))"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE chunks (id VARCHAR PRIMARY KEY, document_id VARCHAR, "
            "ordinal INTEGER, content TEXT)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE relations (id VARCHAR PRIMARY KEY, stable_key VARCHAR(500), "
            "verification_state VARCHAR(30) NOT NULL, confidence FLOAT, "
            "source_entity_id VARCHAR, target_entity_id VARCHAR, "
            "valid_from DATETIME, valid_to DATETIME)"
        )
    )
    return connection


def _bind(module, connection):
    module.op = Operations(MigrationContext.configure(connection))
    return module


def _capacity(connection, table: str, column: str):
    return next(
        getattr(item["type"], "length", None)
        for item in inspect(connection).get_columns(table)
        if item["name"] == column
    )


def _assert_nothing_widened(connection) -> None:
    """The revision must abort before touching any legacy capacity."""
    assert _capacity(connection, "artifacts", "provider_file_id") == 200
    assert _capacity(connection, "documents", "language") == 20
    assert _capacity(connection, "relations", "stable_key") == 500
    assert _capacity(connection, "relations", "verification_state") == 30


# --------------------------------------------------------------------------
# preflight contract
# --------------------------------------------------------------------------


def test_parity_revision_exposes_a_preflight() -> None:
    module = _load("parity_0004_preflight_symbol")
    assert hasattr(module, "preflight")


def test_preflight_passes_on_a_conforming_legacy_database() -> None:
    module = _load("parity_0004_ok")
    connection = _legacy_connection()
    connection.execute(text("INSERT INTO entities VALUES ('e1', 'k1')"))
    connection.execute(text("INSERT INTO entities VALUES ('e2', 'k2')"))
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) "
             "VALUES ('a1', 'f', 'f', 3)")
    )
    connection.execute(
        text("INSERT INTO documents (id, entity_id, artifact_id, language, title) "
             "VALUES ('d1', 'e1', 'a1', 'ko', 't')")
    )
    connection.execute(
        text("INSERT INTO chunks (id, document_id, ordinal, content) "
             "VALUES ('c1', 'd1', 0, 'x')")
    )
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, confidence, "
             "source_entity_id, target_entity_id, valid_from, valid_to) "
             "VALUES ('r1', 'k3', 'unverified', 0.5, 'e1', 'e2', NULL, NULL)")
    )
    _bind(module, connection)
    assert module.preflight() == []


# --------------------------------------------------------------------------
# check violations block the revision
# --------------------------------------------------------------------------


def test_preflight_blocks_negative_artifact_byte_size() -> None:
    module = _load("parity_0004_byte_size")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) "
             "VALUES ('a1', 'f', 'f', -5)")
    )
    _bind(module, connection)
    with pytest.raises(RuntimeError, match="ck_artifact_byte_size"):
        module.preflight()


def test_preflight_blocks_negative_chunk_ordinal() -> None:
    module = _load("parity_0004_ordinal")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO chunks (id, document_id, ordinal, content) "
             "VALUES ('c1', 'd1', -1, 'x')")
    )
    _bind(module, connection)
    with pytest.raises(RuntimeError, match="ck_chunk_ordinal"):
        module.preflight()


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_preflight_blocks_out_of_range_relation_confidence(confidence: float) -> None:
    module = _load(f"parity_0004_confidence_{confidence}")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, confidence) "
             f"VALUES ('r1', 'k', 'unverified', {confidence})")
    )
    _bind(module, connection)
    with pytest.raises(RuntimeError, match="ck_relation_confidence"):
        module.preflight()


def test_preflight_allows_null_confidence() -> None:
    module = _load("parity_0004_confidence_null")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, confidence) "
             "VALUES ('r1', 'k', 'unverified', NULL)")
    )
    _bind(module, connection)
    assert module.preflight() == []


def test_preflight_blocks_relation_self_loop() -> None:
    module = _load("parity_0004_self_loop")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, "
             "source_entity_id, target_entity_id) "
             "VALUES ('r1', 'k', 'unverified', 'e1', 'e1')")
    )
    _bind(module, connection)
    with pytest.raises(RuntimeError, match="ck_relation_no_self_loop"):
        module.preflight()


def test_preflight_blocks_inverted_temporal_window() -> None:
    module = _load("parity_0004_temporal")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, "
             "valid_from, valid_to) "
             "VALUES ('r1', 'k', 'unverified', '2026-01-02', '2026-01-01')")
    )
    _bind(module, connection)
    with pytest.raises(RuntimeError, match="ck_relation_temporal_order"):
        module.preflight()


def test_preflight_allows_open_ended_temporal_window() -> None:
    module = _load("parity_0004_temporal_open")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, valid_from, valid_to) "
             "VALUES ('r1', 'k', 'unverified', '2026-01-01', NULL)")
    )
    _bind(module, connection)
    assert module.preflight() == []


# --------------------------------------------------------------------------
# orphaned foreign keys
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("child_table", "child_column", "statement", "constraint"),
    [
        (
            "chunks",
            "document_id",
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "VALUES ('c1', 'missing', 0, 'x')",
            "fk_chunks_document_id",
        ),
        (
            "relations",
            "source_entity_id",
            "INSERT INTO relations (id, stable_key, verification_state, source_entity_id) "
            "VALUES ('r1', 'k', 'unverified', 'missing')",
            "fk_relations_source_entity_id",
        ),
        (
            "relations",
            "target_entity_id",
            "INSERT INTO relations (id, stable_key, verification_state, target_entity_id) "
            "VALUES ('r1', 'k', 'unverified', 'missing')",
            "fk_relations_target_entity_id",
        ),
    ],
)
def test_preflight_blocks_orphaned_foreign_key_references(
    child_table: str, child_column: str, statement: str, constraint: str
) -> None:
    module = _load(f"parity_0004_orphan_{child_table}_{child_column}")
    connection = _legacy_connection()
    connection.execute(text(statement))
    _bind(module, connection)
    with pytest.raises(RuntimeError, match=constraint):
        module.preflight()


def test_preflight_reports_every_violation_in_one_pass() -> None:
    """The operator gets the full list, not just the first blocking check."""
    module = _load("parity_0004_multi")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) "
             "VALUES ('a1', 'f', 'f', -5)")
    )
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, confidence, "
             "source_entity_id, target_entity_id) "
             "VALUES ('r1', 'k', 'unverified', 4.0, 'missing', 'missing')")
    )
    _bind(module, connection)
    with pytest.raises(RuntimeError) as excinfo:
        module.preflight()
    message = str(excinfo.value)
    assert "preflight failed" in message
    assert "no changes were applied" in message
    for constraint in (
        "ck_artifact_byte_size",
        "ck_relation_confidence",
        "fk_relations_source_entity_id",
        "fk_relations_target_entity_id",
    ):
        assert constraint in message


def test_preflight_is_read_only() -> None:
    module = _load("parity_0004_readonly")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) "
             "VALUES ('a1', 'f', 'f', -5)")
    )
    _bind(module, connection)
    before = connection.execute(text("SELECT count(*) FROM artifacts")).scalar_one()
    with pytest.raises(RuntimeError):
        module.preflight()
    after = connection.execute(text("SELECT count(*) FROM artifacts")).scalar_one()
    assert before == after == 1
    _assert_nothing_widened(connection)


# --------------------------------------------------------------------------
# upgrade ordering: preflight first, then DDL
# --------------------------------------------------------------------------


def test_upgrade_aborts_before_any_widening_on_a_violating_database() -> None:
    module = _load("parity_0004_upgrade_guard")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) "
             "VALUES ('a1', 'f', 'f', -5)")
    )
    _bind(module, connection)

    with pytest.raises(RuntimeError):
        module.upgrade()

    _assert_nothing_widened(connection)
    check_names = {
        check["name"] for check in inspect(connection).get_check_constraints("artifacts")
    }
    assert "ck_artifact_byte_size" not in check_names


def test_upgrade_applies_widenings_and_checks_on_a_conforming_database() -> None:
    module = _load("parity_0004_upgrade_ok")
    connection = _legacy_connection()
    connection.execute(text("INSERT INTO entities VALUES ('e1', 'k1')"))
    connection.execute(text("INSERT INTO entities VALUES ('e2', 'k2')"))
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) "
             "VALUES ('a1', 'f', 'f', 3)")
    )
    connection.execute(
        text("INSERT INTO documents (id, entity_id, language, title) "
             "VALUES ('d1', 'e1', 'ko', 't')")
    )
    connection.execute(
        text("INSERT INTO chunks (id, document_id, ordinal, content) "
             "VALUES ('c1', 'd1', 0, 'x')")
    )
    connection.execute(
        text("INSERT INTO relations (id, stable_key, verification_state, confidence, "
             "source_entity_id, target_entity_id) "
             "VALUES ('r1', 'k3', 'unverified', 0.5, 'e1', 'e2')")
    )
    _bind(module, connection)
    module.upgrade()
    module.downgrade()

    _capacity_widened = {
        ("artifacts", "provider_file_id"): 500,
        ("documents", "language"): 50,
        ("relations", "stable_key"): 700,
        ("relations", "verification_state"): 50,
    }
    inspector = inspect(connection)
    for (table, column), expected in _capacity_widened.items():
        assert _capacity(connection, table, column) == expected
    for table, name in (
        ("artifacts", "ck_artifact_byte_size"),
        ("chunks", "ck_chunk_ordinal"),
        ("relations", "ck_relation_confidence"),
    ):
        names = {check["name"] for check in inspector.get_check_constraints(table)}
        assert name in names
    # the pre-existing data survived the batch rebuild
    assert connection.execute(text("SELECT byte_size FROM artifacts WHERE id = 'a1'")).scalar_one() == 3


def test_upgrade_is_idempotent_on_an_already_parity_database() -> None:
    module = _load("parity_0004_rerun")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO artifacts (id, name, provider_file_id, byte_size) "
             "VALUES ('a1', 'f', 'f', 3)")
    )
    _bind(module, connection)
    module.upgrade()
    module.upgrade()

    inspector = inspect(connection)
    for table, name in (
        ("artifacts", "ck_artifact_byte_size"),
        ("chunks", "ck_chunk_ordinal"),
        ("relations", "ck_relation_confidence"),
    ):
        names = [check["name"] for check in inspector.get_check_constraints(table)]
        assert names.count(name) == 1


# --------------------------------------------------------------------------
# skipped tables and preserved contracts
# --------------------------------------------------------------------------


def test_preflight_skips_tables_a_legacy_database_does_not_have() -> None:
    module = _load("parity_0004_partial_schema")
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text("CREATE TABLE artifacts (id VARCHAR PRIMARY KEY, provider_file_id VARCHAR(200), "
             "byte_size BIGINT)")
    )
    _bind(module, connection)
    assert module.preflight() == []


def test_preflight_skips_checks_whose_columns_are_absent() -> None:
    """A column a legacy database lacks cannot violate the predicate."""
    module = _load("parity_0004_absent_column")
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text("CREATE TABLE chunks (id VARCHAR PRIMARY KEY, document_id VARCHAR, content TEXT)")
    )
    _bind(module, connection)
    assert module.preflight() == []


def test_downgrade_remains_a_no_op() -> None:
    source = PARITY_MIGRATION.read_text(encoding="utf-8")
    assert "def downgrade() -> None:" in source
    assert "return None" in source
    for destructive in (
        "op.drop_table",
        "op.drop_column",
        "op.drop_constraint",
        "op.batch_alter_table(table) as batch:\n        batch.drop",
    ):
        assert destructive not in source


def test_0002_and_0003_preflight_and_downgrade_contracts_are_untouched() -> None:
    evidence = (ROOT / "migrations/versions/0002_evidence_contract.py").read_text(encoding="utf-8")
    vector = (ROOT / "migrations/versions/0003_vector_embeddings.py").read_text(encoding="utf-8")
    assert "def preflight() -> list[str]:" in evidence
    assert "def preflight() -> list[str]:" in vector
    assert "raise NotImplementedError" in evidence
    assert "op.drop_table" not in vector
