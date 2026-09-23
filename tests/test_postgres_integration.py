from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

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
