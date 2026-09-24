from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/rehearse-postgres.ps1"
DOC = ROOT / "docs/POSTGRES_REHEARSAL.md"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_rehearsal_pins_postgres_and_pgvector() -> None:
    source = _script()
    assert 'pgvector/pgvector:0.8.6-pg16' in source
    assert 'pull $Image' in source
    assert 'POSTGRES_PASSWORD=$password' in source
    assert "127.0.0.1:$hostPort" in source
    assert "postgresql+psycopg://postgres:$password@127.0.0.1" in source


def test_rehearsal_uses_only_generated_temporary_resources() -> None:
    source = _script()
    assert '[guid]::NewGuid().ToString("N")' in source
    assert "sion-pg-rehearsal-$suffix" in source
    assert "type=volume,source=$volumeName" in source
    assert 'label "purpose=sion-postgres-rehearsal"' in source
    assert "docker compose" not in source.lower()
    assert "docker-compose" not in source.lower()
    assert "docker system prune" not in source.lower()
    assert "rm --force $containerName" in source
    assert "volume rm --force $volumeName" in source


def test_rehearsal_covers_migration_seed_constraints_vectors_and_readiness() -> None:
    source = _script()
    for evidence in (
        "upgrade 0001_baseline",
        "upgrade head",
        "seed_core_types(session)",
        "pg_constraint",
        "expected check violation",
        "INSERT INTO embeddings",
        "<=>",
        "check_readiness(engine, vector_enabled=True)",
        'assert result["status"] == "ready"',
    ):
        assert evidence in source


def test_downgrade_contract_is_non_destructive_and_explicit() -> None:
    source = _script()
    assert "downgrade 0002_evidence_contract" in source
    assert 'revision == "0002_evidence_contract"' in source
    assert "(entity_count, embedding_count, extension_count) == (1, 1, 1)" in source
    migration = ROOT / "migrations/versions/0003_vector_embeddings.py"
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert values["revision"] == "0003_vector_embeddings"
    assert values["down_revision"] == "0002_evidence_contract"
    assert "op.drop_table" not in migration.read_text(encoding="utf-8")


def test_documentation_contains_reproduction_and_manual_fallback() -> None:
    source = _doc()
    assert "scripts/rehearse-postgres.ps1" in source
    assert "pgvector/pgvector:0.8.6-pg16" in source
    assert "SION_ALEMBIC_EXECUTE_SCHEMA_CREATE=1" in source
    assert "alembic upgrade 0001_baseline" in source
    assert "alembic upgrade head" in source
    assert "downgrade 0002_evidence_contract" in source
    assert "운영 DB" in source
    assert "수동 명령" in source
    assert "readiness" in source.lower()
