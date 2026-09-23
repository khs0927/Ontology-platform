import pytest
from pydantic import ValidationError

from ontology_map_bridge import MapExport, build_import_plan


def valid_payload():
    return {
        "schema_version": "ontology-map-export/v1",
        "namespace": "current-map",
        "source": "structured-source",
        "source_uri": "example://map-source",
        "expected_node_count": 2,
        "expected_relation_count": 1,
        "categories": [{"id": "core", "label": "핵심 체계"}],
        "nodes": [
            {"id": "n1", "label": "Ontology Store", "entity_type_id": "SystemComponent", "category_id": "core"},
            {"id": "n2", "label": "Evidence Ledger", "entity_type_id": "SystemComponent", "category_id": "core"},
        ],
        "relations": [
            {"id": "r1", "source_id": "n1", "target_id": "n2", "relation_type_id": "SUPPORTS"}
        ],
    }


def test_structured_map_contract_accepts_consistent_graph():
    export = MapExport.model_validate(valid_payload())
    assert len(export.nodes) == 2
    assert len(export.relations) == 1


def test_structured_map_contract_rejects_dangling_edge():
    payload = valid_payload()
    payload["relations"][0]["target_id"] = "missing"
    with pytest.raises(ValidationError, match="unknown relation target_id"):
        MapExport.model_validate(payload)


def test_structured_map_contract_rejects_count_mismatch():
    payload = valid_payload()
    payload["expected_relation_count"] = 43
    with pytest.raises(ValidationError, match="relation count mismatch"):
        MapExport.model_validate(payload)


def test_import_plan_preserves_counts_and_builds_provenance():
    export = MapExport.model_validate(valid_payload())
    plan = build_import_plan(export)

    assert len(plan.entities) == 2
    assert len(plan.relations) == 1
    assert len(plan.evidence) == 1
    assert plan.entities[0].stable_key == "map:current-map:node:n1"
    assert plan.relations[0].stable_key == "map:current-map:relation:r1"
    assert plan.relations[0].source_stable_key == "map:current-map:node:n1"
    assert plan.relations[0].target_stable_key == "map:current-map:node:n2"
    assert plan.evidence[0].source_uri == "example://map-source"
    assert plan.evidence[0].verification_state == "unverified"
