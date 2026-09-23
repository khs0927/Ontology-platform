from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ontology_api import models
from ontology_api.main import create_app


POSTGRES_URL = os.getenv("ONTOLOGY_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ONTOLOGY_TEST_POSTGRES_URL is not configured")


def test_postgres_entity_relation_artifact_evidence_flow():
    suffix = uuid4().hex
    with TestClient(create_app(POSTGRES_URL)) as client:
        health = client.get("/health/db")
        assert health.status_code == 200, health.text
        assert health.json() == {"status": "ok", "database": "postgresql"}

        project = client.post("/entities", json={
            "stable_key": f"ci:project:{suffix}",
            "entity_type_id": "Project",
            "name": f"CI Project {suffix[:8]}",
            "category": "core",
        })
        assert project.status_code == 201, project.text

        tool = client.post("/entities", json={
            "stable_key": f"ci:tool:{suffix}",
            "entity_type_id": "Tool",
            "name": f"CI Tool {suffix[:8]}",
            "category": "ai_automation",
        })
        assert tool.status_code == 201, tool.text

        relation = client.post("/relations", json={
            "stable_key": f"ci:relation:{suffix}",
            "source_entity_id": project.json()["id"],
            "target_entity_id": tool.json()["id"],
            "relation_type_id": "USES",
            "confidence": 1.0,
            "verification_state": "machine_verified",
            "source_kind": "api",
        })
        assert relation.status_code == 201, relation.text

        artifact = client.post("/artifacts", json={
            "stable_key": f"ci:artifact:{suffix}",
            "name": "ci.txt",
            "storage_uri": f"test://ci/{suffix}",
            "content_hash": "sha256:" + ("b" * 64),
            "mime_type": "text/plain",
            "byte_size": 1,
            "provider": "ci",
            "provider_file_id": suffix,
        })
        assert artifact.status_code == 201, artifact.text

        evidence = client.post("/evidence", json={
            "relation_id": relation.json()["id"],
            "artifact_id": artifact.json()["id"],
            "source_uri": f"test://ci/{suffix}",
            "source_locator": "integration-test",
            "verification_state": "machine_verified",
        })
        assert evidence.status_code == 201, evidence.text

        fetched = client.get(f"/relations/{relation.json()['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["relation_type_id"] == "USES"


def test_postgres_canonical_integrity_graph_and_chunk_evidence():
    suffix = uuid4().hex
    app = create_app(POSTGRES_URL)
    entity_id = backing_id = None
    with TestClient(app) as client:
        try:
            entity = client.post("/entities", json={
                "stable_key": f"pg:entity:{suffix}",
                "entity_type_id": "Document",
                "name": "Integration document",
                "category": "core",
            })
            assert entity.status_code == 201, entity.text
            entity_id = entity.json()["id"]

            backing = client.post("/entities", json={
                "stable_key": f"pg:backing:{suffix}",
                "entity_type_id": "Dataset",
                "name": "Integration dataset",
            })
            assert backing.status_code == 201, backing.text
            backing_id = backing.json()["id"]
            artifact = client.post("/artifacts", json={
                "stable_key": f"pg:artifact:{suffix}",
                "entity_id": backing_id,
                "name": "dataset.txt",
                "storage_uri": f"test://pg/{suffix}",
            })
            assert artifact.status_code == 201, artifact.text
            artifact_id = artifact.json()["id"]
            assert artifact.json()["entity_id"] == backing_id
            assert any(node["id"] == backing_id for node in client.get("/graph").json()["nodes"])

            with app.state.database.SessionLocal() as db:
                document = models.Document(entity_id=entity_id, artifact_id=artifact_id, title="integration")
                db.add(document)
                db.flush()
                chunk = models.Chunk(document_id=document.id, ordinal=0, content="evidence text")
                db.add(chunk)
                db.commit()
                chunk_id = chunk.id

            missing = client.post("/evidence", json={"entity_id": entity_id, "chunk_id": str(uuid4())})
            assert missing.status_code == 422
            evidence = client.post("/evidence", json={"entity_id": entity_id, "chunk_id": chunk_id})
            assert evidence.status_code == 201, evidence.text
            evidence_id = evidence.json()["id"]
            artifact_evidence = client.post("/evidence", json={"entity_id": entity_id, "artifact_id": artifact_id})
            assert artifact_evidence.status_code == 201, artifact_evidence.text

            bad_loop = client.post("/relations", json={
                "stable_key": f"pg:bad-loop:{suffix}",
                "source_entity_id": entity_id,
                "target_entity_id": entity_id,
                "relation_type_id": "USES",
            })
            assert bad_loop.status_code == 409

            assert client.delete(f"/entities/{backing_id}").status_code == 204
            backing_id = None
            assert client.get(f"/artifacts/{artifact_id}").status_code == 404
            assert client.get(f"/evidence/{artifact_evidence.json()['id']}").status_code == 404
            with app.state.database.SessionLocal() as db:
                assert db.get(models.Document, document.id).artifact_id is None

            assert client.delete(f"/entities/{entity_id}").status_code == 204
            entity_id = None
            assert client.get(f"/evidence/{evidence_id}").status_code == 404
            with app.state.database.engine.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM chunks WHERE id = CAST(:id AS uuid)"), {"id": chunk_id}).scalar_one() == 0
        finally:
            if entity_id:
                client.delete(f"/entities/{entity_id}")
            if backing_id:
                client.delete(f"/entities/{backing_id}")


def test_postgres_map_import_is_atomic_and_available_in_graph():
    suffix = uuid4().hex
    payload = {
        "namespace": f"pg-integration-{suffix}",
        "source": "integration",
        "source_uri": f"test://map/{suffix}",
        "expected_node_count": 2,
        "expected_relation_count": 1,
        "categories": [{"id": "core", "label": "Core"}],
        "nodes": [
            {"id": "left", "label": "Left", "entity_type_id": "Concept", "category_id": "core"},
            {"id": "right", "label": "Right", "entity_type_id": "Concept", "category_id": "core"},
        ],
        "relations": [{"id": "edge", "source_id": "left", "target_id": "right", "relation_type_id": "RELATED_TO"}],
    }
    with TestClient(create_app(POSTGRES_URL)) as client:
        try:
            created = client.post("/imports/map", json=payload)
            assert created.status_code == 201, created.text
            assert created.json()["entities_created"] == 2
            assert created.json()["relations_created"] == 1
            assert created.json()["evidence_created"] == 1
            assert client.post("/imports/map", json=payload).status_code == 409
            graph = client.get("/graph").json()
            imported = [row for row in graph["relations"] if row["stable_key"] == f"map:pg-integration-{suffix}:relation:edge"]
            assert len(imported) == 1
            evidence = client.get(f"/relations/{imported[0]['id']}/evidence").json()
            assert len(evidence) == 1
            assert evidence[0]["source_uri"] == payload["source_uri"]
        finally:
            # Remove only rows created by this test. Relation and Evidence cascade.
            graph = client.get("/graph").json()
            for node in graph["nodes"]:
                if node["stable_key"].startswith(f"map:pg-integration-{suffix}:node:"):
                    client.delete(f"/entities/{node['id']}")
