from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations/versions/0003_vector_embeddings.py"


def test_vector_migration_is_followed_by_0003_contract() -> None:
    source = MIGRATION.read_text()
    tree = ast.parse(source)
    values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
    assert values["revision"] == "0003_vector_embeddings"
    assert values["down_revision"] == "0002_evidence_contract"
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
    assert "embeddings" in source
    assert "ck_embeddings_shape" in source
    assert "uq_embeddings_entity_model_content" in source
    assert "idx_embeddings_model_dimensions" in source
    assert "return None" in source


def test_sqlite_is_smoke_only_when_vectors_are_requested() -> None:
    from sqlalchemy import create_engine, text
    from sion_api.health import check_readiness
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in ("entity_types", "relation_types", "entities", "ontology_versions", "artifacts", "documents", "chunks", "relations", "evidence"):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
    result = check_readiness(engine, vector_enabled=True)
    assert result["status"] == "not_ready"
    assert result["components"]["revision"]["status"] == "ok"
    assert result["components"]["vector"]["reason"] == "vector_postgres_required"
