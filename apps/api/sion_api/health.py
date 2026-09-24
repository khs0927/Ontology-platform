from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[3]
CORE_TABLES = frozenset({"entity_types", "relation_types", "entities", "ontology_versions", "artifacts", "documents", "chunks", "relations", "evidence"})
VECTOR_TABLE = "embeddings"

def _vector_enabled() -> bool:
    return os.getenv("SION_VECTOR_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

def _component(ok: bool, reason: str | None = None) -> dict[str, Any]:
    return {"status": "ok" if ok else "failed", "reason": reason}

def _alembic_head() -> str | None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()

def _vector_contract_ok(connection: Any, tables: set[str]) -> tuple[bool, str | None]:
    if connection.dialect.name != "postgresql":
        return False, "vector_postgres_required"
    extension_ok = bool(connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar_one())
    type_ok = bool(connection.execute(text("SELECT to_regtype('vector') IS NOT NULL")).scalar_one())
    if not extension_ok: return False, "vector_extension_missing"
    if not type_ok: return False, "vector_type_missing"
    if VECTOR_TABLE not in tables: return False, "embeddings_table_missing"
    columns = {column["name"] for column in inspect(connection).get_columns(VECTOR_TABLE)}
    if not {"id", "entity_id", "chunk_id", "model", "dimensions", "embedding"}.issubset(columns):
        return False, "embeddings_columns_missing"
    return True, None

def check_readiness(engine: Engine, *, vector_enabled: bool | None = None) -> dict[str, Any]:
    vector_checked = _vector_enabled() if vector_enabled is None else vector_enabled
    components: dict[str, dict[str, Any]] = {}
    database_ok = schema_ok = revision_ok = vector_ok = False
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            database_ok = True
            tables = set(inspect(connection).get_table_names())
            schema_ok = CORE_TABLES.issubset(tables)
            components["schema"] = _component(schema_ok, None if schema_ok else "core_schema_missing")
            if connection.dialect.name == "postgresql":
                head = _alembic_head()
                revisions = ({row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))} if "alembic_version" in tables else set())
                revision_ok = head is not None and revisions == {head}
                components["revision"] = _component(revision_ok, None if revision_ok else ("alembic_revision_missing" if not revisions else "alembic_revision_mismatch"))
            else:
                revision_ok = True
                components["revision"] = _component(True)
            if vector_checked:
                vector_ok, reason = _vector_contract_ok(connection, tables)
            else:
                vector_ok, reason = True, None
            components["vector"] = _component(vector_ok, reason)
    except Exception:
        components.setdefault("database", _component(False, "database_unavailable"))
        components.setdefault("schema", _component(False, "schema_check_failed"))
        components.setdefault("revision", _component(False, "revision_check_failed"))
        components.setdefault("vector", _component(False, "vector_check_failed"))
        database_ok = False
    components.setdefault("database", _component(database_ok, None if database_ok else "database_unavailable"))
    ready = database_ok and schema_ok and revision_ok and vector_ok
    return {"status": "ready" if ready else "not_ready", "service": "sion-ontology-api", "components": components}
