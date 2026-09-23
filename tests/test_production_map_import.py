import json
from pathlib import Path
from fastapi.testclient import TestClient

from ontology_api.main import create_app
from ontology_map_bridge import build_import_plan, load_map_export


PRODUCTION_EXPORT_PATH = Path("data/bootstrap/sion-map-production.json")
INVENTORY_PATH = Path("data/bootstrap/current-map-inventory.json")


def test_production_map_export_matches_inventory():
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    export = load_map_export(PRODUCTION_EXPORT_PATH)

    assert export.expected_node_count == 31
    assert export.expected_relation_count == 43
    assert len(export.nodes) == 31
    assert len(export.relations) == 43

    # Check visible labels match inventory exactly
    export_labels = {node.label for node in export.nodes}
    inventory_labels = set(inventory["visible_labels"])
    assert export_labels == inventory_labels

    # Check category counts match inventory
    category_counts = {}
    for node in export.nodes:
        category_counts[node.category_id] = category_counts.get(node.category_id, 0) + 1

    for cat in inventory["categories"]:
        assert category_counts[cat["id"]] == cat["observed_count"]


def test_production_import_plan_structure():
    export = load_map_export(PRODUCTION_EXPORT_PATH)
    plan = build_import_plan(export)

    assert len(plan.entities) == 31
    assert len(plan.relations) == 43
    assert len(plan.evidence) == 43

    # Ensure stable keys are deterministic and prefixed
    for entity in plan.entities:
        assert entity.stable_key.startswith("map:sion-production:node:")
    for rel in plan.relations:
        assert rel.stable_key.startswith("map:sion-production:relation:")
    for ev in plan.evidence:
        assert ev.relation_stable_key.startswith("map:sion-production:relation:")
        assert ev.source_uri == "sion://ontology-map/production/v1"
        assert ev.verification_state == "unverified"


def test_production_map_import_via_api():
    payload = json.loads(PRODUCTION_EXPORT_PATH.read_text(encoding="utf-8"))

    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        # Import production map
        response = client.post("/imports/map", json=payload)
        assert response.status_code == 201, response.text
        assert response.json() == {
            "namespace": "sion-production",
            "entities_created": 31,
            "relations_created": 43,
            "evidence_created": 43,
        }

        # Verify /graph endpoint
        graph_resp = client.get("/graph")
        assert graph_resp.status_code == 200
        graph_data = graph_resp.json()
        assert len(graph_data["nodes"]) == 31
        assert len(graph_data["relations"]) == 43

        # Verify /evidence endpoint
        evidence_resp = client.get("/evidence")
        assert evidence_resp.status_code == 200
        evidence_data = evidence_resp.json()
        assert len(evidence_data) == 43

        # Conflict on re-import
        reimport_resp = client.post("/imports/map", json=payload)
        assert reimport_resp.status_code == 409
