"""Rebuildable Apache AGE projection. Canonical tables stay the source of truth."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session


GRAPH_NAME = "sion_graph"
CREATE_GRAPH = """
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('sion_graph');
"""  # first-time bootstrap; prefer ensure_graph() / migrations/005 (idempotent)


def ensure_graph(session: Session) -> None:
    """Create the AGE extension/graph if missing (idempotent)."""
    session.execute(text("CREATE EXTENSION IF NOT EXISTS age"))
    session.execute(text("LOAD 'age'"))
    session.execute(text('SET search_path = ag_catalog, "$user", public'))
    exists = session.execute(
        text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = :name"), {"name": GRAPH_NAME}
    ).first()
    if not exists:
        session.execute(text("SELECT ag_catalog.create_graph(:name)"), {"name": GRAPH_NAME})


def rebuild_projection(session: Session) -> int:
    """Rebuild the AGE graph from canonical tables. Returns statements executed."""
    statements = projection_cypher(session)
    ensure_graph(session)
    for statement in statements:
        session.connection().exec_driver_sql(statement)
    return len(statements)


_LABEL_SAFE = re.compile(r"[^A-Za-z0-9_]")


def _label(raw: object) -> str:
    """Return a Cypher-safe label; AGE labels must be plain identifiers."""
    label = _LABEL_SAFE.sub("_", str(raw)) or "Unlabeled"
    return label if not label[0].isdigit() else f"L_{label}"


def _literal(raw: object) -> str:
    return str(raw).replace("\\", "\\\\").replace("'", "\\'").replace("$$", "$ $")


def projection_cypher(session: Session) -> list[str]:
    statements = ["SELECT * FROM cypher('sion_graph', $$ MATCH (n) DETACH DELETE n $$) AS (v agtype);"]
    entities = session.execute(text("SELECT stable_key, entity_type_id, name FROM entities")).mappings()
    for row in entities:
        label = _label(row["entity_type_id"])
        key = _literal(row["stable_key"])
        name = _literal(row["name"])
        statements.append(
            "SELECT * FROM cypher('sion_graph', $$ "
            f"CREATE (:{label} {{stable_key: '{key}', name: '{name}'}}) "
            "$$) AS (v agtype);"
        )
    relations = session.execute(
        text(
            """
            SELECT r.stable_key, r.relation_type_id, s.stable_key AS source_key, t.stable_key AS target_key
            FROM relations r
            JOIN entities s ON s.id = r.source_entity_id
            JOIN entities t ON t.id = r.target_entity_id
            WHERE r.valid_to IS NULL
            """
        )
    ).mappings()
    for row in relations:
        label = _label(row["relation_type_id"])
        source = _literal(row["source_key"])
        target = _literal(row["target_key"])
        edge = _literal(row["stable_key"])
        statements.append(
            "SELECT * FROM cypher('sion_graph', $$ "
            f"MATCH (a {{stable_key: '{source}'}}), (b {{stable_key: '{target}'}}) "
            f"CREATE (a)-[:{label} {{stable_key: '{edge}'}}]->(b) "
            "$$) AS (v agtype);"
        )
    return statements
