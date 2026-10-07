"""Rebuildable Apache AGE projection. Canonical tables stay the source of truth."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


CREATE_GRAPH = """
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('sion_graph');
"""


def projection_cypher(session: Session) -> list[str]:
    statements = ["SELECT * FROM cypher('sion_graph', $$ MATCH (n) DETACH DELETE n $$) AS (v agtype);"]
    entities = session.execute(text("SELECT stable_key, entity_type_id, name FROM entities")).mappings()
    for row in entities:
        label = str(row["entity_type_id"]).replace("`", "")
        key = str(row["stable_key"]).replace("'", "\\'")
        name = str(row["name"]).replace("'", "\\'")
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
        label = str(row["relation_type_id"]).replace("`", "")
        source = str(row["source_key"]).replace("'", "\\'")
        target = str(row["target_key"]).replace("'", "\\'")
        edge = str(row["stable_key"]).replace("'", "\\'")
        statements.append(
            "SELECT * FROM cypher('sion_graph', $$ "
            f"MATCH (a {{stable_key: '{source}'}}), (b {{stable_key: '{target}'}}) "
            f"CREATE (a)-[:{label} {{stable_key: '{edge}'}}]->(b) "
            "$$) AS (v agtype);"
        )
    return statements
