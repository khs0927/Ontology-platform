from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/0002_evidence_contract.py"
VECTOR_MIGRATION = ROOT / "migrations/versions/0003_vector_embeddings.py"
PARITY_MIGRATION = ROOT / "migrations/versions/0004_schema_parity.py"
MODELS = ROOT / "apps/api/sion_api/models.py"


def _source() -> str:
    return MIGRATION.read_text()


def test_revision_chain_and_additive_safety() -> None:
    tree = ast.parse(_source())
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}
    assert values["revision"] == "0002_evidence_contract"
    assert values["down_revision"] == "0001_baseline"
    assert "op.drop_column" not in _source()
    assert "NotImplementedError" in _source()


def test_evidence_and_relation_constraints_are_named_and_dialect_aware() -> None:
    source = _source()
    for name in (
        "ck_evidence_source",
        "ck_evidence_target_xor",
        "ck_evidence_excerpt_hash",
        "ck_relation_no_self_loop",
        "ck_relation_temporal_order",
        "ck_relation_verification_state",
    ):
        assert name in source
    assert "artifact_id" in source and "chunk_id" in source and "source_uri" in source
    assert "sha256:" in source and "verification_state" in source
    assert "postgresql" in source and "GLOB" in source
    assert 'batch.create_check_constraint(name, expression)' in source
    assert "create_check_constraint(sa.CheckConstraint" not in source


def test_migration_contract_matches_model_check_names() -> None:
    models = MODELS.read_text()
    for name in (
        "ck_evidence_source",
        "ck_evidence_target_xor",
        "ck_evidence_excerpt_hash",
        "ck_relation_no_self_loop",
        "ck_relation_temporal_order",
        "ck_relation_verification_state",
        "ck_evidence_verification_state",
        "ck_artifact_byte_size",
        "ck_chunk_ordinal",
        "ck_relation_confidence",
    ):
        assert name in models
    assert "ck_evidence_target_xor" in models
    assert "source_entity_id <> target_entity_id" in models
    assert "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from" in models


def test_vector_revision_is_additive_and_non_destructive() -> None:
    source = VECTOR_MIGRATION.read_text()
    tree = ast.parse(source)
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}
    assert values["revision"] == "0003_vector_embeddings"
    assert values["down_revision"] == "0002_evidence_contract"
    for name in ("ck_embeddings_dimensions_positive", "ck_embeddings_shape", "ck_embeddings_target_xor", "uq_embeddings_entity_model_content", "uq_embeddings_chunk_model_content", "idx_embeddings_model_dimensions"):
        assert name in source
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
    assert "class Vector(UserDefinedType)" in source
    assert 'return "VECTOR"' in source
    assert "postgresql.VECTOR" not in source
    assert "op.drop_table" not in source
    assert "return None" in source


def test_schema_parity_revision_extends_0003_without_destructive_downgrade() -> None:
    source = PARITY_MIGRATION.read_text()
    tree = ast.parse(source)
    values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert values["revision"] == "0004_schema_parity"
    assert values["down_revision"] == "0003_vector_embeddings"
    assert "def downgrade() -> None:" in source
    assert "return None" in source
    for destructive in ("op.drop_column", "op.drop_table", "op.drop_constraint"):
        assert destructive not in source


def test_schema_parity_contains_canonical_capacity_repairs() -> None:
    source = PARITY_MIGRATION.read_text()
    tree = ast.parse(source)
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_CAPACITY_PARITY" for target in node.targets)
    )
    repairs = [ast.literal_eval(element) for element in assignment.value.elts]
    assert ("artifacts", "provider_file_id", 200, 500) in repairs
    assert ("documents", "language", 20, 50) in repairs
    assert ("documents", "title", 500, None) in repairs
    assert ("relations", "stable_key", 500, 700) in repairs
    assert ("relations", "verification_state", 30, 50) in repairs
    assert all(
        target is None or target > legacy
        for _, _, legacy, target in repairs
    )


def test_schema_parity_has_dialect_guards_and_named_check_repairs() -> None:
    source = PARITY_MIGRATION.read_text()
    assert '"postgresql"' in source
    assert '"sqlite"' in source
    assert "op.alter_column" in source
    assert "batch.alter_column" in source
    assert "batch.create_check_constraint" in source
    for name in (
        "ck_artifact_byte_size",
        "ck_chunk_ordinal",
        "ck_relation_confidence",
    ):
        assert name in source
    assert "if name in existing:" in source
    assert "unsupported schema-parity dialect" in source


def test_schema_parity_executes_on_sqlite_with_batch_rebuild_and_no_op_downgrade() -> None:
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Text, create_engine, inspect, text

    spec = importlib.util.spec_from_file_location("schema_parity_0004", PARITY_MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE artifacts (id VARCHAR PRIMARY KEY, provider_file_id VARCHAR(200), byte_size BIGINT)"))
        connection.execute(text("CREATE TABLE documents (id VARCHAR PRIMARY KEY, language VARCHAR(20), title VARCHAR(500))"))
        connection.execute(text("CREATE TABLE relations (id VARCHAR PRIMARY KEY, stable_key VARCHAR(500), verification_state VARCHAR(30) NOT NULL, confidence FLOAT)"))
        connection.execute(text("CREATE TABLE chunks (id VARCHAR PRIMARY KEY, ordinal INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO artifacts VALUES ('a', 'provider-id', 3)"))

        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.downgrade()

        inspector = inspect(connection)
        capacities = {
            (table, column["name"]): getattr(column["type"], "length", None)
            for table in ("artifacts", "documents", "relations")
            for column in inspector.get_columns(table)
        }
        assert capacities[("artifacts", "provider_file_id")] == 500
        assert capacities[("documents", "language")] == 50
        assert capacities[("relations", "stable_key")] == 700
        assert capacities[("relations", "verification_state")] == 50
        title_type = next(
            column["type"]
            for column in inspector.get_columns("documents")
            if column["name"] == "title"
        )
        assert isinstance(title_type, Text)

        check_names = {
            (table, check["name"])
            for table in ("artifacts", "chunks", "relations")
            for check in inspector.get_check_constraints(table)
        }
        assert ("artifacts", "ck_artifact_byte_size") in check_names
        assert ("chunks", "ck_chunk_ordinal") in check_names
        assert ("relations", "ck_relation_confidence") in check_names
        assert connection.execute(text("SELECT byte_size FROM artifacts WHERE id = 'a'")).scalar_one() == 3
