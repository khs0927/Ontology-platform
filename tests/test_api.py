from fastapi.testclient import TestClient

from ontology_api.main import create_app


def client() -> TestClient:
    return TestClient(create_app("sqlite+pysqlite:///:memory:"))


def test_health():
    with client() as c:
        assert c.get("/health").json() == {"status": "ok"}
        assert c.get("/health/db").json() == {"status": "ok", "database": "sqlite"}


def test_entity_relation_evidence_flow():
    with client() as c:
        a = c.post("/entities", json={"stable_key":"project:alpha","entity_type_id":"Project","name":"Alpha","description":"Architecture project","category":"architecture_site"})
        assert a.status_code == 201, a.text
        b = c.post("/entities", json={"stable_key":"tool:cad","entity_type_id":"Tool","name":"CAD Bridge","category":"cad_bim"})
        assert b.status_code == 201, b.text
        relation = c.post("/relations", json={"stable_key":"rel:alpha-uses-cad","source_entity_id":a.json()["id"],"target_entity_id":b.json()["id"],"relation_type_id":"USES","confidence":0.95})
        assert relation.status_code == 201, relation.text
        evidence = c.post("/evidence", json={"relation_id":relation.json()["id"],"source_uri":"file:///example.md","source_locator":"L1-L3","verification_state":"human_verified"})
        assert evidence.status_code == 201, evidence.text
        query = c.get("/query/entities", params={"q":"Alpha"})
        assert query.status_code == 200
        assert [x["stable_key"] for x in query.json()] == ["project:alpha"]


def test_legacy_type_aliases_are_accepted():
    with client() as c:
        entity = c.post("/entities", json={"stable_key":"concept:legacy","entity_type":"Concept","name":"Legacy Alias"})
        assert entity.status_code == 201
        assert entity.json()["entity_type_id"] == "Concept"


def test_unknown_types_are_rejected():
    with client() as c:
        assert c.post("/entities", json={"stable_key":"bad:type","entity_type_id":"NotAType","name":"Bad"}).status_code == 422


def test_duplicate_entity_is_conflict():
    with client() as c:
        payload = {"stable_key":"concept:x","entity_type_id":"Concept","name":"X"}
        assert c.post("/entities", json=payload).status_code == 201
        assert c.post("/entities", json=payload).status_code == 409


def test_entity_update_and_delete():
    with client() as c:
        created = c.post("/entities", json={"stable_key":"project:beta","entity_type_id":"Project","name":"Beta"})
        entity_id = created.json()["id"]
        updated = c.patch(f"/entities/{entity_id}", json={"name":"Beta Updated"})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Beta Updated"
        deleted = c.delete(f"/entities/{entity_id}")
        assert deleted.status_code == 204
        assert c.get(f"/entities/{entity_id}").status_code == 404


def test_artifact_metadata_and_evidence_link():
    with client() as c:
        entity = c.post("/entities", json={"stable_key":"document:one","entity_type_id":"Document","name":"Document One"})
        artifact = c.post("/artifacts", json={
            "stable_key":"artifact:one",
            "name":"one.txt",
            "storage_uri":"gdrive://file-123",
            "content_hash":"sha256:" + ("a" * 64),
            "mime_type":"text/plain",
            "byte_size":12,
            "provider":"google-drive",
            "provider_file_id":"file-123"
        })
        assert artifact.status_code == 201, artifact.text
        evidence = c.post("/evidence", json={
            "entity_id":entity.json()["id"],
            "artifact_id":artifact.json()["id"],
            "verification_state":"machine_verified"
        })
        assert evidence.status_code == 201, evidence.text
        assert evidence.json()["artifact_id"] == artifact.json()["id"]
