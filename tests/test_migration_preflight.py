"""Focused tests for the migration preflight and constraint contracts.

These tests exercise ``0002_evidence_contract`` and ``0003_vector_embeddings``
against a real SQLite database so the read-only preflight, the evidence
provenance foreign keys and the dialect-specific ``sha256:`` prefix handling are
covered without requiring a live PostgreSQL server.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).parents[1]
EVIDENCE_MIGRATION = ROOT / "migrations/versions/0002_evidence_contract.py"
VECTOR_MIGRATION = ROOT / "migrations/versions/0003_vector_embeddings.py"
PARITY_MIGRATION = ROOT / "migrations/versions/0004_schema_parity.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revision_chain() -> dict[str, str | None]:
    chain: dict[str, str | None] = {}
    for path in sorted((ROOT / "migrations/versions").glob("0*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        }
        chain[values["revision"]] = values["down_revision"]
    return chain


def _legacy_connection():
    """A minimal pre-0002 database shaped like the legacy SQL migrations."""
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text(
            "CREATE TABLE artifacts (id VARCHAR PRIMARY KEY, content_hash VARCHAR(200))"
        )
    )
    connection.execute(text("CREATE TABLE chunks (id VARCHAR PRIMARY KEY, ordinal INTEGER)"))
    connection.execute(
        text(
            "CREATE TABLE relations ("
            "id VARCHAR PRIMARY KEY, source_entity_id VARCHAR, target_entity_id VARCHAR, "
            "valid_from DATETIME, valid_to DATETIME)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE evidence ("
            "id VARCHAR PRIMARY KEY, entity_id VARCHAR, relation_id VARCHAR, "
            "artifact_id VARCHAR, chunk_id VARCHAR, source_uri TEXT, "
            "excerpt_hash VARCHAR(200), confidence FLOAT, verification_state VARCHAR(30) "
            "NOT NULL DEFAULT 'unverified')"
        )
    )
    return connection


def _bind_operations(module, connection):
    module.op = Operations(MigrationContext.configure(connection))
    return module


# --------------------------------------------------------------------------
# chain integrity
# --------------------------------------------------------------------------


def test_migration_chain_remains_linear_and_unchanged() -> None:
    chain = _revision_chain()
    assert chain == {
        "0001_baseline": None,
        "0002_evidence_contract": "0001_baseline",
        "0003_vector_embeddings": "0002_evidence_contract",
        "0004_schema_parity": "0003_vector_embeddings",
    }


def test_downgrade_semantics_are_preserved() -> None:
    evidence = EVIDENCE_MIGRATION.read_text(encoding="utf-8")
    vector = VECTOR_MIGRATION.read_text(encoding="utf-8")
    parity = PARITY_MIGRATION.read_text(encoding="utf-8")
    # 0002 refuses destructive rollback, 0003/0004 are explicit no-ops.
    assert "raise NotImplementedError" in evidence
    for source in (vector, parity):
        assert "def downgrade() -> None:" in source
        assert "return None" in source
        for destructive in ("op.drop_table", "op.drop_column", "op.drop_constraint", "DROP TABLE"):
            assert destructive not in source


# --------------------------------------------------------------------------
# 0002 preflight
# --------------------------------------------------------------------------


def test_preflight_passes_on_conforming_legacy_rows() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_ok")
    connection = _legacy_connection()
    connection.execute(text("INSERT INTO artifacts VALUES ('a1', 'sha256:" + "0" * 64 + "')"))
    connection.execute(
        text(
            "INSERT INTO evidence (id, entity_id, artifact_id, verification_state) "
            "VALUES ('e1', 'ent', 'a1', 'human_verified')"
        )
    )
    _bind_operations(module, connection)
    assert module.preflight() == []


def test_preflight_blocks_evidence_without_any_provenance_source() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_no_source")
    connection = _legacy_connection()
    connection.execute(
        text(
            "INSERT INTO evidence (id, entity_id, verification_state) "
            "VALUES ('e1', 'ent', 'unverified')"
        )
    )
    _bind_operations(module, connection)
    with pytest.raises(RuntimeError) as excinfo:
        module.preflight()
    message = str(excinfo.value)
    assert "preflight failed" in message
    assert "ck_evidence_source" in message


def test_preflight_blocks_target_xor_violation() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_xor")
    connection = _legacy_connection()
    connection.execute(
        text(
            "INSERT INTO evidence (id, entity_id, relation_id, source_uri, verification_state) "
            "VALUES ('e1', 'ent', 'rel', 's3://bucket/x', 'unverified')"
        )
    )
    _bind_operations(module, connection)
    with pytest.raises(RuntimeError, match="ck_evidence_target_xor"):
        module.preflight()


def test_preflight_blocks_orphaned_evidence_artifact_reference() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_orphan")
    connection = _legacy_connection()
    connection.execute(
        text(
            "INSERT INTO evidence (id, entity_id, artifact_id, verification_state) "
            "VALUES ('e1', 'ent', 'missing-artifact', 'unverified')"
        )
    )
    _bind_operations(module, connection)
    with pytest.raises(RuntimeError, match="fk_evidence_artifact_id"):
        module.preflight()


def test_preflight_blocks_self_loop_relations() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_loop")
    connection = _legacy_connection()
    connection.execute(
        text("INSERT INTO relations VALUES ('r1', 'e1', 'e1', NULL, NULL)")
    )
    _bind_operations(module, connection)
    with pytest.raises(RuntimeError, match="ck_relation_no_self_loop"):
        module.preflight()


def test_preflight_rejects_non_sha256_excerpt_hash_prefix() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_prefix")
    connection = _legacy_connection()
    connection.execute(
        text(
            "INSERT INTO evidence (id, entity_id, source_uri, excerpt_hash, verification_state) "
            "VALUES ('e1', 'ent', 's3://b/x', 'md5:0123456789abcdef0123456789abcdef"
            "0123456789abcdef0123456789abcdef', 'unverified')"
        )
    )
    _bind_operations(module, connection)
    with pytest.raises(RuntimeError, match="ck_evidence_excerpt_hash"):
        module.preflight()


def test_postgres_hash_expression_requires_literal_sha256_prefix() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_pg_expr")
    source = EVIDENCE_MIGRATION.read_text(encoding="utf-8")
    assert "substring(excerpt_hash from 1 for 7) = 'sha256:'" in source
    assert module is not None
    # the old prefix-blind expression must be gone
    assert "length(excerpt_hash) = 71 AND substring(excerpt_hash from 8)" not in source


# --------------------------------------------------------------------------
# 0002 upgrade behaviour on a legacy database
# --------------------------------------------------------------------------


def test_upgrade_adds_evidence_foreign_keys_and_named_checks() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_upgrade")
    connection = _legacy_connection()
    connection.execute(text("INSERT INTO artifacts VALUES ('a1', NULL)"))
    connection.execute(
        text(
            "INSERT INTO evidence (id, entity_id, artifact_id, verification_state) "
            "VALUES ('e1', 'ent', 'a1', 'unverified')"
        )
    )
    _bind_operations(module, connection)
    module.upgrade()

    inspector = inspect(connection)
    check_names = {check["name"] for check in inspector.get_check_constraints("evidence")}
    assert "ck_evidence_source" in check_names
    assert "ck_evidence_target_xor" in check_names
    assert "ck_evidence_excerpt_hash" in check_names
    assert "ck_evidence_verification_state" in check_names

    foreign_keys = {
        (fk["constrained_columns"][0], fk["referred_table"])
        for fk in inspector.get_foreign_keys("evidence")
        if fk["constrained_columns"]
    }
    assert ("artifact_id", "artifacts") in foreign_keys
    assert ("chunk_id", "chunks") in foreign_keys

    # pre-existing provenance data survived the upgrade
    assert (
        connection.execute(text("SELECT artifact_id FROM evidence WHERE id = 'e1'")).scalar_one()
        == "a1"
    )


def test_upgrade_is_idempotent_on_a_contract_compliant_database() -> None:
    module = _load(EVIDENCE_MIGRATION, "evidence_0002_rerun")
    connection = _legacy_connection()
    connection.execute(text("INSERT INTO artifacts VALUES ('a1', NULL)"))
    connection.execute(text("INSERT INTO chunks VALUES ('c1', 0)"))
    connection.execute(
        text(
            "INSERT INTO evidence (id, entity_id, artifact_id, chunk_id, verification_state) "
            "VALUES ('e1', 'ent', 'a1', 'c1', 'unverified')"
        )
    )
    _bind_operations(module, connection)
    module.upgrade()
    module.upgrade()  # guards must skip existing constraints

    names = [
        fk["name"]
        for fk in inspect(connection).get_foreign_keys("evidence")
        if fk["name"]
    ]
    assert len(names) == len(set(names))


# --------------------------------------------------------------------------
# 0003 preflight and null content_hash policy
# --------------------------------------------------------------------------


def test_vector_preflight_flags_duplicate_content_hash_groups() -> None:
    module = _load(VECTOR_MIGRATION, "vector_0003_preflight")
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text(
            "CREATE TABLE embeddings (id VARCHAR PRIMARY KEY, entity_id VARCHAR, "
            "chunk_id VARCHAR, model VARCHAR, dimensions INTEGER, content_hash VARCHAR)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO embeddings VALUES ('x1', 'e1', NULL, 'm', 4, 'sha256:aaa'), "
            "('x2', 'e1', NULL, 'm', 4, 'sha256:aaa')"
        )
    )
    _bind_operations(module, connection)
    with pytest.raises(RuntimeError, match="uq_embeddings_entity_model_hash"):
        module.preflight()


def test_vector_preflight_allows_null_content_hash_duplicates() -> None:
    module = _load(VECTOR_MIGRATION, "vector_0003_null_hash")
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text(
            "CREATE TABLE embeddings (id VARCHAR PRIMARY KEY, entity_id VARCHAR, "
            "chunk_id VARCHAR, model VARCHAR, dimensions INTEGER, content_hash VARCHAR)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO embeddings VALUES ('x1', 'e1', NULL, 'm', 4, NULL), "
            "('x2', 'e1', NULL, 'm', 4, NULL)"
        )
    )
    _bind_operations(module, connection)
    assert module.preflight() == []


def test_vector_partial_unique_index_policy_excludes_null_hashes() -> None:
    source = VECTOR_MIGRATION.read_text(encoding="utf-8")
    assert "uq_embeddings_entity_model_hash" in source
    assert "uq_embeddings_chunk_model_hash" in source
    assert "entity_id IS NOT NULL AND content_hash IS NOT NULL" in source
    assert "chunk_id IS NOT NULL AND content_hash IS NOT NULL" in source
    assert "postgresql_where=sa.text(predicate)" in source
    assert "NULLS NOT DISTINCT" in source
    # the destructive downgrade no-op contract is intact
    assert "op.drop_table" not in source


def test_vector_preflight_is_read_only_for_a_provisioned_database() -> None:
    module = _load(VECTOR_MIGRATION, "vector_0003_readonly")
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text(
            "CREATE TABLE embeddings (id VARCHAR PRIMARY KEY, entity_id VARCHAR, "
            "chunk_id VARCHAR, model VARCHAR, dimensions INTEGER, content_hash VARCHAR)"
        )
    )
    connection.execute(text("INSERT INTO embeddings VALUES ('x1', 'e1', NULL, 'm', 4, NULL)"))
    _bind_operations(module, connection)
    before = connection.execute(text("SELECT count(*) FROM embeddings")).scalar_one()
    module.preflight()
    after = connection.execute(text("SELECT count(*) FROM embeddings")).scalar_one()
    assert before == after == 1


def test_vector_upgrade_still_refuses_non_postgres_dialects() -> None:
    module = _load(VECTOR_MIGRATION, "vector_0003_dialect")
    engine = create_engine("sqlite://")
    connection = engine.connect()
    _bind_operations(module, connection)
    with pytest.raises(RuntimeError, match="requires PostgreSQL with pgvector"):
        module.upgrade()


def test_ddl_role_and_extension_privilege_guidance_is_documented() -> None:
    source = VECTOR_MIGRATION.read_text(encoding="utf-8")
    assert "DDL role and extension privileges" in source
    assert "CREATE EXTENSION" in source
    assert "insufficientPrivilege" in source
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
