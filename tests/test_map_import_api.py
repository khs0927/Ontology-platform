from fastapi.testclient import TestClient

from ontology_api.main import create_app


def payload():
    return {
        "schema_version": "ontology-map-export/v1",
        "namespace": "api-import-test",
        "source": "structured-test-source",
        "source_uri": "test://map-source",
        "expected_node_count": 2,
        "expected_relation_count": 1,
        "categories": [{"id": "core", "label": "핵심 체계"}],
        "nodes": [
            {"id": "a", "label": "Node A", "entity_type_id": "Concept", "category_id": "core"},
            {"id": "b", "label": "Node B", "entity_type_id": "Concept", "category_id": "core"},
        ],
        "relations": [
            {
                "id": "r",
                "source_id": "a",
                "target_id": "b",
                "relation_type_id": "RELATED_TO",
                "source_locator": "edge:r",
            }
        ],
    }


def test_map_import_is_atomic_and_populates_graph():
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        imported = client.post("/imports/map", json=payload())
        assert imported.status_code == 201, imported.text
        assert imported.json() == {
            "namespace": "api-import-test",
            "entities_created": 2,
            "relations_created": 1,
            "evidence_created": 1,
        }

        graph = client.get("/graph")
        assert graph.status_code == 200
        assert {node["stable_key"] for node in graph.json()["nodes"]} == {
            "map:api-import-test:node:a",
            "map:api-import-test:node:b",
        }
        assert [relation["stable_key"] for relation in graph.json()["relations"]] == [
            "map:api-import-test:relation:r"
        ]

        evidence = client.get("/evidence")
        assert evidence.status_code == 200
        assert len(evidence.json()) == 1
        assert evidence.json()[0]["source_uri"] == "test://map-source"
        assert evidence.json()[0]["verification_state"] == "unverified"

        repeated = client.post("/imports/map", json=payload())
        assert repeated.status_code == 409


def test_map_import_rejects_unknown_canonical_types_without_partial_write():
    bad = payload()
    bad["nodes"][1]["entity_type_id"] = "UnknownType"

    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        response = client.post("/imports/map", json=bad)
        assert response.status_code == 422
        graph = client.get("/graph").json()
        assert graph == {"nodes": [], "relations": []}


def test_map_import_rejects_invalid_self_loop_without_partial_write():
    bad = payload()
    bad["relations"][0]["target_id"] = "a"
    bad["relations"][0]["relation_type_id"] = "USES"
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        response = client.post("/imports/map", json=bad)
        assert response.status_code == 422
        assert client.get("/graph").json() == {"nodes": [], "relations": []}
