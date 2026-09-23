from fastapi.testclient import TestClient

from ontology_api.main import create_app


def test_relation_explain_returns_endpoints_and_provenance():
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as c:
        source = c.post("/entities", json={
            "stable_key": "explain:source",
            "entity_type_id": "Concept",
            "name": "Source",
        })
        target = c.post("/entities", json={
            "stable_key": "explain:target",
            "entity_type_id": "Concept",
            "name": "Target",
        })
        relation = c.post("/relations", json={
            "stable_key": "explain:relation",
            "source_entity_id": source.json()["id"],
            "target_entity_id": target.json()["id"],
            "relation_type_id": "SUPPORTS",
            "source_kind": "imported",
        })
        evidence = c.post("/evidence", json={
            "relation_id": relation.json()["id"],
            "source_uri": "test://source-document",
            "source_locator": "page:7",
            "verification_state": "human_verified",
        })
        assert evidence.status_code == 201, evidence.text

        response = c.get(f"/relations/{relation.json()['id']}/explain")
        assert response.status_code == 200
        body = response.json()
        assert body["source"]["stable_key"] == "explain:source"
        assert body["target"]["stable_key"] == "explain:target"
        assert body["relation"]["stable_key"] == "explain:relation"
        assert len(body["evidence"]) == 1
        assert body["evidence"][0]["source_uri"] == "test://source-document"
        assert body["evidence"][0]["source_locator"] == "page:7"

        relation_evidence = c.get(f"/relations/{relation.json()['id']}/evidence")
        assert relation_evidence.status_code == 200
        assert relation_evidence.json()[0]["verification_state"] == "human_verified"
