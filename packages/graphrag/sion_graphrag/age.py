"""Rebuildable Apache AGE projection. Canonical tables stay the source of truth."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

GRAPH_NAME = "sion_graph"

# First-time bootstrap only (fails if the graph exists); prefer ensure_graph().
CREATE_GRAPH = """
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('sion_graph');
"""

_LABEL_UNSAFE = re.compile(r"[^A-Za-z0-9_]")


def _label(raw: object) -> str:
    """Return a Cypher-safe vertex/edge label.

    AGE labels are plain identifiers and are interpolated into the Cypher text,
    so anything outside ``[A-Za-z0-9_]`` is replaced and a leading digit is prefixed.
    """
    label = _LABEL_UNSAFE.sub("_", str(raw)) or "Unlabeled"
    return f"L_{label}" if label[0].isdigit() else label


def _literal(raw: object) -> str:
    """Escape a value for a single-quoted Cypher string inside a ``$$`` SQL block.

    ``$$`` would terminate the dollar-quoted cypher() argument early, so every run of
    dollar signs is broken up (repeat until none is left: ``$$$$`` -> ``$ $ $ $``).
    """
    value = str(raw).replace("\\", "\\\\").replace("'", "\\'")
    while "$$" in value:
        value = value.replace("$$", "$ $")
    return value


def ensure_graph(session: Session) -> None:
    """Create the AGE extension and graph when missing; safe to call repeatedly."""
    session.execute(text("CREATE EXTENSION IF NOT EXISTS age"))
    session.execute(text("LOAD 'age'"))
    session.execute(text('SET search_path = ag_catalog, "$user", public'))
    exists = session.execute(
        text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = :name"), {"name": GRAPH_NAME}
    ).first()
    if not exists:
        session.execute(text("SELECT ag_catalog.create_graph(:name)"), {"name": GRAPH_NAME})


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
