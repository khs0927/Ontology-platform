"""Core relation-type vocabulary stays in sync across SQLite seed, ingestion and Postgres."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sion_api import migrate, models
from sion_api.db import Base, build_engine, build_session_factory
from sion_api.repository import seed_core_types
from sion_ingestion.agent_bridge import AgentOntologyBridge
from sion_ingestion.graph_export import KNOWN_RELATION_TYPES, normalize_relation_type
from sion_ingestion.map_import import MapExport, import_map_export

ROOT = Path(__file__).resolve().parents[1]
COEXISTENCE = ROOT / "data" / "bootstrap" / "hueflow-mcp2-coexistence-20261027.json"
_RELATION_ROW = re.compile(r"\(\s*'([A-Z_]+)',\s*'[^']*',\s*NULL")


def _session_factory():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = build_session_factory(engine)
    with sf() as session:
        seed_core_types(session)
    return sf


def _postgres_relation_types() -> set[str]:
    found: set[str] = set()
    for version in migrate.CORE_SEQUENCE:
        sql = (migrate.CORE_DIR / f"{version}.sql").read_text(encoding="utf-8")
        for block in re.findall(r"INSERT INTO relation_types.*?;", sql, flags=re.DOTALL):
            found.update(_RELATION_ROW.findall(block))
    return found


def test_seed_known_types_and_postgres_migrations_agree():
    with _session_factory()() as session:
        seeded = {row.id for row in session.query(models.RelationType).all()}
    assert seeded == set(KNOWN_RELATION_TYPES)
    assert _postgres_relation_types() == set(KNOWN_RELATION_TYPES)


def test_agent_bridge_postgres_dump_declares_every_known_type():
    empty = MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "t",
            "expected_node_count": 0,
            "expected_edge_count": 0,
            "nodes": [],
            "edges": [],
        }
    )
    sql = AgentOntologyBridge.export_to_postgres_sql(empty)
    block = re.search(r"INSERT INTO relation_types.*?;", sql, flags=re.DOTALL)
    assert block is not None
    assert set(_RELATION_ROW.findall(block.group(0))) == set(KNOWN_RELATION_TYPES)


def test_coexistence_bootstrap_imports_without_remapping():
    export = MapExport.model_validate(json.loads(COEXISTENCE.read_text(encoding="utf-8")))
    used = {edge.relation_type_id for edge in export.edges}
    assert used <= KNOWN_RELATION_TYPES
    for type_id in used:
        assert normalize_relation_type(type_id) == (type_id, None)
    with _session_factory()() as session:
        report = import_map_export(session, export)
        assert report.created_nodes == export.expected_node_count
        assert report.created_edges == export.expected_edge_count
        stored = {row.relation_type_id for row in session.query(models.Relation).all()}
    assert stored == used
