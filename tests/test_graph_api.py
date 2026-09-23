from fastapi.testclient import TestClient

from ontology_api.main import create_app


def test_graph_endpoint_returns_nodes_and_relations():
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as c:
        a = c.post("/entities", json={
            "stable_key": "graph:a",
            "entity_type_id": "Concept",
            "name": "Graph A",
        })
        b = c.post("/entities", json={
            "stable_key": "graph:b",
            "entity_type_id": "Concept",
            "name": "Graph B",
        })
        relation = c.post("/relations", json={
            "stable_key": "graph:r",
            "source_entity_id": a.json()["id"],
            "target_entity_id": b.json()["id"],
            "relation_type_id": "RELATED_TO",
        })
        assert relation.status_code == 201, relation.text

        graph = c.get("/graph")
        assert graph.status_code == 200
        payload = graph.json()
        assert {n["stable_key"] for n in payload["nodes"]} == {"graph:a", "graph:b"}
        assert [r["stable_key"] for r in payload["relations"]] == ["graph:r"]
