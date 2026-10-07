#!/usr/bin/env python3
"""Verify the optional Apache AGE projection against a live PostgreSQL+AGE.

Usage: SION_TEST_AGE_URL=postgresql+psycopg://... python scripts/verify_age.py
Expects migrations 001 and 004 applied. Uses a synthetic two-node fixture
(clearly marked test data); it never touches the real Sion map.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from sion_graphrag.age import GRAPH_NAME, rebuild_projection
from sion_ingestion.map_import import MapExport, import_map_export

FIXTURE = {
    "schema": "sion-map-export/v1",
    "source": "ci-age-fixture",
    "expected_node_count": 2,
    "expected_edge_count": 1,
    "nodes": [
        {"stable_key": "ci:age:doc", "entity_type_id": "Document", "name": "CI fixture doc"},
        {"stable_key": "ci:age:concept", "entity_type_id": "Concept", "name": "CI fixture o'concept"},
    ],
    "edges": [
        {
            "stable_key": "ci:age:edge",
            "source_stable_key": "ci:age:concept",
            "target_stable_key": "ci:age:doc",
            "relation_type_id": "EXTRACTED_FROM",
        }
    ],
}


def main() -> int:
    url = os.environ.get("SION_TEST_AGE_URL")
    if not url:
        print("SION_TEST_AGE_URL not set; skipping AGE verification")
        return 0
    engine = create_engine(url)
    with Session(engine) as session:
        import_map_export(session, MapExport.model_validate(FIXTURE))
        session.commit()
    for _ in range(2):  # rebuild must be repeatable
        with Session(engine) as session:
            rebuild_projection(session)
            session.commit()
    with engine.connect() as conn:
        conn.execute(text("LOAD 'age'"))
        conn.execute(text('SET search_path = ag_catalog, "$user", public'))
        vertices = conn.exec_driver_sql(
            f"SELECT * FROM cypher('{GRAPH_NAME}', $$ MATCH (n) RETURN count(n) $$) AS (c agtype)"
        ).scalar()
        edges = conn.exec_driver_sql(
            f"SELECT * FROM cypher('{GRAPH_NAME}', $$ MATCH ()-[r]->() RETURN count(r) $$) AS (c agtype)"
        ).scalar()
    print(f"AGE projection: vertices={vertices} edges={edges}")
    if int(str(vertices)) < 2 or int(str(edges)) < 1:
        print("AGE projection did not contain the fixture", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
