from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from ontology_api import models
from ontology_api.main import create_app


CORE_TABLES = {
    "ontology_versions",
    "entity_types",
    "relation_types",
    "entities",
    "artifacts",
    "documents",
    "chunks",
    "relations",
    "evidence",
}


def test_sqlite_foreign_keys_are_enabled_before_use():
    app = create_app("sqlite+pysqlite:///:memory:")
    with app.state.database.engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_sqlite_metadata_matches_core_migration_tables():
    app = create_app("sqlite+pysqlite:///:memory:")
    with app.state.database.engine.connect() as conn:
        tables = set(
            conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars()
        )
    assert CORE_TABLES <= tables


def test_invalid_chunk_evidence_is_rejected_before_database_error():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        entity = client.post(
            "/entities",
            json={"stable_key": "chunk:entity", "entity_type_id": "Document", "name": "Chunk Entity"},
        )
        assert entity.status_code == 201
        response = client.post(
            "/evidence",
            json={"entity_id": entity.json()["id"], "chunk_id": str(uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "chunk not found"


def test_valid_chunk_evidence_uses_real_foreign_key():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        entity = client.post(
            "/entities",
            json={"stable_key": "chunk:doc", "entity_type_id": "Document", "name": "Doc"},
        )
        artifact = client.post(
            "/artifacts",
            json={"stable_key": "chunk:artifact", "name": "doc.txt", "storage_uri": "test://doc"},
        )
        with app.state.database.SessionLocal() as db:
            document = models.Document(
                entity_id=entity.json()["id"],
                artifact_id=artifact.json()["id"],
                title="Doc",
            )
            db.add(document)
            db.flush()
            chunk = models.Chunk(document_id=document.id, ordinal=0, content="hello", locator="p1")
            db.add(chunk)
            db.commit()
            chunk_id = chunk.id

        evidence = client.post(
            "/evidence",
            json={"entity_id": entity.json()["id"], "chunk_id": chunk_id},
        )
        assert evidence.status_code == 201, evidence.text
        assert evidence.json()["chunk_id"] == chunk_id


def test_non_related_self_loop_is_rejected_by_sqlite_constraint():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        entity = client.post(
            "/entities",
            json={"stable_key": "loop:x", "entity_type_id": "Concept", "name": "Loop"},
        )
        entity_id = entity.json()["id"]

        bad = client.post(
            "/relations",
            json={
                "stable_key": "loop:bad",
                "source_entity_id": entity_id,
                "target_entity_id": entity_id,
                "relation_type_id": "USES",
            },
        )
        assert bad.status_code == 409

        good = client.post(
            "/relations",
            json={
                "stable_key": "loop:ok",
                "source_entity_id": entity_id,
                "target_entity_id": entity_id,
                "relation_type_id": "RELATED_TO",
            },
        )
        assert good.status_code == 201, good.text


def test_entity_delete_cascades_relation_and_evidence():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        source = client.post(
            "/entities",
            json={"stable_key": "cascade:a", "entity_type_id": "Concept", "name": "A"},
        )
        target = client.post(
            "/entities",
            json={"stable_key": "cascade:b", "entity_type_id": "Concept", "name": "B"},
        )
        relation = client.post(
            "/relations",
            json={
                "stable_key": "cascade:r",
                "source_entity_id": source.json()["id"],
                "target_entity_id": target.json()["id"],
                "relation_type_id": "RELATED_TO",
            },
        )
        evidence = client.post(
            "/evidence",
            json={"relation_id": relation.json()["id"], "source_uri": "test://cascade"},
        )
        assert evidence.status_code == 201

        assert client.delete(f"/entities/{source.json()['id']}").status_code == 204
        assert client.get(f"/relations/{relation.json()['id']}").status_code == 404
        assert client.get(f"/evidence/{evidence.json()['id']}").status_code == 404


def test_invalid_category_and_source_kind_are_rejected_by_api_contract():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        bad_category = client.post(
            "/entities",
            json={"stable_key": "bad:category", "entity_type_id": "Concept", "name": "Bad", "category": "made_up"},
        )
        assert bad_category.status_code == 422

        source = client.post(
            "/entities",
            json={"stable_key": "kind:a", "entity_type_id": "Concept", "name": "A"},
        )
        target = client.post(
            "/entities",
            json={"stable_key": "kind:b", "entity_type_id": "Concept", "name": "B"},
        )
        bad_kind = client.post(
            "/relations",
            json={
                "stable_key": "kind:r",
                "source_entity_id": source.json()["id"],
                "target_entity_id": target.json()["id"],
                "relation_type_id": "RELATED_TO",
                "source_kind": "made_up",
            },
        )
        assert bad_kind.status_code == 422


def test_map_import_rejects_noncanonical_category_before_write():
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = {
        "schema_version": "ontology-map-export/v1",
        "namespace": "bad-category-map",
        "source": "structured-source",
        "source_uri": "test://bad-category-map",
        "expected_node_count": 1,
        "expected_relation_count": 0,
        "categories": [{"id": "custom", "label": "Custom"}],
        "nodes": [
            {"id": "n1", "label": "Node", "entity_type_id": "Concept", "category_id": "custom"}
        ],
        "relations": [],
    }
    with TestClient(app) as client:
        response = client.post("/imports/map", json=payload)
        assert response.status_code == 422
        assert "unknown knowledge categories" in response.json()["detail"]
        assert client.get("/graph").json() == {"nodes": [], "relations": []}


def test_artifact_can_link_to_graph_entity_without_breaking_legacy_records():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        graph_entity = client.post(
            "/entities",
            json={"stable_key": "artifact:linked", "entity_type_id": "Artifact", "name": "Linked Artifact"},
        )
        linked = client.post(
            "/artifacts",
            json={
                "entity_id": graph_entity.json()["id"],
                "stable_key": "artifact:linked",
                "name": "linked.bin",
                "storage_uri": "test://linked",
            },
        )
        assert linked.status_code == 201, linked.text
        assert linked.json()["entity_id"] == graph_entity.json()["id"]

        legacy = client.post(
            "/artifacts",
            json={"stable_key": "artifact:legacy", "name": "legacy.bin", "storage_uri": "test://legacy"},
        )
        assert legacy.status_code == 201, legacy.text
        assert legacy.json()["entity_id"] is None


def test_artifact_link_rejects_wrong_entity_type_and_duplicate_link():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        concept = client.post(
            "/entities",
            json={"stable_key": "artifact:concept", "entity_type_id": "Concept", "name": "Not Artifact"},
        )
        wrong = client.post(
            "/artifacts",
            json={
                "entity_id": concept.json()["id"],
                "stable_key": "artifact:wrong",
                "name": "wrong.bin",
                "storage_uri": "test://wrong",
            },
        )
        assert wrong.status_code == 422

        entity = client.post(
            "/entities",
            json={"stable_key": "artifact:one-entity", "entity_type_id": "Dataset", "name": "Dataset"},
        )
        first = client.post(
            "/artifacts",
            json={
                "entity_id": entity.json()["id"],
                "stable_key": "artifact:first",
                "name": "first.bin",
                "storage_uri": "test://first",
            },
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/artifacts",
            json={
                "entity_id": entity.json()["id"],
                "stable_key": "artifact:second",
                "name": "second.bin",
                "storage_uri": "test://second",
            },
        )
        assert second.status_code == 409


def test_deleting_artifact_graph_entity_cascades_linked_artifact_metadata():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        entity = client.post(
            "/entities",
            json={"stable_key": "artifact:cascade", "entity_type_id": "Deliverable", "name": "Deliverable"},
        )
        artifact = client.post(
            "/artifacts",
            json={
                "entity_id": entity.json()["id"],
                "stable_key": "artifact:cascade-metadata",
                "name": "deliverable.pdf",
                "storage_uri": "test://deliverable",
            },
        )
        assert artifact.status_code == 201, artifact.text
        assert client.delete(f"/entities/{entity.json()['id']}").status_code == 204
        assert client.get(f"/artifacts/{artifact.json()['id']}").status_code == 404


def test_linked_artifact_delete_keeps_document_and_removes_evidence():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        linked = client.post("/entities", json={
            "stable_key": "cascade:artifact:entity", "entity_type_id": "Artifact", "name": "Source"
        })
        document_entity = client.post("/entities", json={
            "stable_key": "cascade:document:entity", "entity_type_id": "Document", "name": "Document"
        })
        artifact = client.post("/artifacts", json={
            "stable_key": "cascade:artifact:metadata", "entity_id": linked.json()["id"],
            "name": "source.txt", "storage_uri": "test://source"
        })
        assert artifact.status_code == 201, artifact.text
        document_id = str(uuid4())
        with app.state.database.SessionLocal() as db:
            db.add(models.Document(
                id=document_id, entity_id=document_entity.json()["id"],
                artifact_id=artifact.json()["id"], title="Keep this document"
            ))
            db.commit()
        evidence = client.post("/evidence", json={
            "entity_id": document_entity.json()["id"], "artifact_id": artifact.json()["id"]
        })
        assert evidence.status_code == 201, evidence.text

        assert client.delete(f"/entities/{linked.json()['id']}").status_code == 204
        assert client.get(f"/artifacts/{artifact.json()['id']}").status_code == 404
        assert client.get(f"/evidence/{evidence.json()['id']}").status_code == 404
        with app.state.database.SessionLocal() as db:
            assert db.get(models.Document, document_id).artifact_id is None
