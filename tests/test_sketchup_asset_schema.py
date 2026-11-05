"""Schema and referential-integrity checks for the SketchUp asset source data."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ROOT / "data/sources/sketchup/object-classes.json"
CLASSIFICATION = ROOT / "data/sources/sketchup/0914-meeting/classification.json"
BOOTSTRAP = ROOT / "data/bootstrap/sketchup-0914-meeting.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_object_classes_have_required_fields_and_unique_ids():
    data = _load(CLASSES)
    assert data["schema"] == "sion-sketchup-object-classes/v1"
    classes = data["classes"]
    required = {"id", "label_ko", "label_en", "category", "description_ko"}

    assert classes
    assert all(required <= set(item) for item in classes)
    ids = [item["id"] for item in classes]
    assert len(ids) == len(set(ids))
    assert all(isinstance(item, str) and item for item in ids)


def test_classification_has_required_fields_and_known_class_references():
    classes = {item["id"] for item in _load(CLASSES)["classes"]}
    data = _load(CLASSIFICATION)
    assignments = data["assignments"]
    required = {"definition", "class", "confidence", "basis_ko"}

    assert data["schema"] == "sion-sketchup-classification/v1"
    assert assignments
    assert all(required <= set(item) for item in assignments)
    assert len({item["definition"] for item in assignments}) == len(assignments)
    assert {item["class"] for item in assignments} <= classes
    assert all(0.0 <= item["confidence"] <= 1.0 for item in assignments)
    assert all(item["basis_ko"].strip() for item in assignments)


def test_bootstrap_edges_reference_existing_nodes():
    data = _load(BOOTSTRAP)
    nodes = data["nodes"]
    edges = data["edges"]
    node_keys = [node["stable_key"] for node in nodes]
    required_node = {
        "stable_key",
        "entity_type_id",
        "name",
        "category",
        "description",
        "external_uri",
        "properties",
        "ontology_version",
    }
    required_edge = {
        "stable_key",
        "source_stable_key",
        "target_stable_key",
        "relation_type_id",
        "confidence",
        "verification_state",
        "source_kind",
        "ontology_version",
        "properties",
    }

    assert data["schema"] == "sion-map-export/v1"
    assert len(node_keys) == len(set(node_keys))
    assert all(required_node <= set(node) for node in nodes)
    assert all(required_edge <= set(edge) for edge in edges)
    assert data["expected_node_count"] == len(nodes)
    assert data["expected_edge_count"] == len(edges)

    for edge in edges:
        assert edge["source_stable_key"] in node_keys
        assert edge["target_stable_key"] in node_keys
