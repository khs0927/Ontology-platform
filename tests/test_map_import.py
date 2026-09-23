from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from sion_api.db import Base, build_engine, build_session_factory
from sion_api.repository import seed_core_types
from sion_ingestion.map_import import MapExport, import_map_export


def factory():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = build_session_factory(engine)
    with sf() as session:
        seed_core_types(session)
    return sf


def test_import_is_non_destructive_and_idempotent():
    export = MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": "test",
            "expected_node_count": 2,
            "expected_edge_count": 1,
            "nodes": [
                {
                    "stable_key": "project:a",
                    "entity_type_id": "Project",
                    "name": "A",
                },
                {
                    "stable_key": "tool:b",
                    "entity_type_id": "Tool",
                    "name": "B",
                },
            ],
            "edges": [
                {
                    "stable_key": "project:a:USES:tool:b",
                    "source_stable_key": "project:a",
                    "target_stable_key": "tool:b",
                    "relation_type_id": "USES",
                }
            ],
        }
    )
    sf = factory()
    with sf() as session:
        first = import_map_export(session, export)
        assert first.model_dump() == {
            "created_nodes": 2,
            "skipped_nodes": 0,
            "created_edges": 1,
            "skipped_edges": 0,
        }
        second = import_map_export(session, export)
        assert second.model_dump() == {
            "created_nodes": 0,
            "skipped_nodes": 2,
            "created_edges": 0,
            "skipped_edges": 1,
        }


def test_export_rejects_dangling_edges():
    with pytest.raises(ValidationError, match="dangling edge"):
        MapExport.model_validate(
            {
                "schema": "sion-map-export/v1",
                "source": "test",
                "nodes": [
                    {
                        "stable_key": "project:a",
                        "entity_type_id": "Project",
                        "name": "A",
                    }
                ],
                "edges": [
                    {
                        "stable_key": "bad",
                        "source_stable_key": "project:a",
                        "target_stable_key": "missing:b",
                        "relation_type_id": "USES",
                    }
                ],
            }
        )


def test_export_rejects_count_mismatch():
    with pytest.raises(ValidationError, match="node count mismatch"):
        MapExport.model_validate(
            {
                "schema": "sion-map-export/v1",
                "source": "test",
                "expected_node_count": 31,
                "expected_edge_count": 43,
                "nodes": [],
                "edges": [],
            }
        )
