from __future__ import annotations

import json

from fastapi.testclient import TestClient

from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_ingestion.project_contracts import ProjectContractCatalog


def client() -> TestClient:
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    return TestClient(app)


def test_health_and_inventory():
    with client() as c:
        health = c.get("/health")
        assert health.status_code == 200
        assert health.json()["database"] == "sqlite"

        inventory = c.get("/api/v1/bootstrap/map-inventory")
        assert inventory.status_code == 200
        body = inventory.json()
        assert body["observed_node_count"] == 31
        assert body["observed_relation_count"] == 43
        assert len(body["visible_labels"]) == 31


def test_entity_relation_evidence_graph_round_trip():
    with client() as c:
        project = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "project:sion-ontology",
                "entity_type_id": "Project",
                "name": "Sion Ontology",
                "category": "core",
                "properties": {},
            },
        )
        assert project.status_code == 201, project.text

        tool = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "tool:fastapi",
                "entity_type_id": "Tool",
                "name": "FastAPI",
                "category": "ai_automation",
                "properties": {"role": "api"},
            },
        )
        assert tool.status_code == 201, tool.text

        relation = c.post(
            "/api/v1/relations",
            json={
                "stable_key": "project:sion-ontology:USES:tool:fastapi",
                "source_entity_id": project.json()["id"],
                "target_entity_id": tool.json()["id"],
                "relation_type_id": "USES",
                "confidence": 1.0,
                "verification_state": "human_verified",
                "source_kind": "user",
                "properties": {},
            },
        )
        assert relation.status_code == 201, relation.text

        evidence = c.post(
            "/api/v1/evidence",
            json={
                "relation_id": relation.json()["id"],
                "source_uri": "urn:test:user-confirmed",
                "source_locator": "test",
                "confidence": 1.0,
                "verification_state": "human_verified",
                "properties": {},
            },
        )
        assert evidence.status_code == 201, evidence.text

        graph = c.get("/api/v1/graph")
        assert graph.status_code == 200
        body = graph.json()
        assert body["node_count"] == 2
        assert body["edge_count"] == 1
        assert body["edges"][0]["type"] == "USES"


def test_rejects_unknown_references_and_duplicates():
    with client() as c:
        entity = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "concept:test",
                "entity_type_id": "Concept",
                "name": "Test",
                "properties": {},
            },
        )
        assert entity.status_code == 201

        duplicate = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "concept:test",
                "entity_type_id": "Concept",
                "name": "Duplicate",
                "properties": {},
            },
        )
        assert duplicate.status_code == 409

        missing = c.post(
            "/api/v1/relations",
            json={
                "stable_key": "bad",
                "source_entity_id": entity.json()["id"],
                "target_entity_id": "00000000-0000-0000-0000-000000000001",
                "relation_type_id": "RELATED_TO",
                "properties": {},
            },
        )
        assert missing.status_code == 422


def test_rejects_invalid_evidence_without_target():
    with client() as c:
        result = c.post(
            "/api/v1/evidence",
            json={
                "source_uri": "urn:test",
                "properties": {},
            },
        )
        assert result.status_code == 422


def test_vector_endpoints_require_postgres_pgvector():
    with client() as c:
        result = c.post(
            "/api/v1/vector/search",
            json={
                "model": "test/free-model",
                "embedding": [1.0, 0.0, 0.0],
                "limit": 5,
            },
        )
        assert result.status_code == 503
        assert "PostgreSQL" in result.json()["detail"]


def test_embedding_requires_exactly_one_target():
    with client() as c:
        result = c.post(
            "/api/v1/embeddings",
            json={
                "model": "test/free-model",
                "embedding": [1.0, 0.0, 0.0],
                "properties": {},
            },
        )
        assert result.status_code == 422


def test_artifact_metadata_round_trip_and_duplicate_guard():
    with client() as c:
        payload = {
            "stable_key": "artifact:sha256:" + "a" * 64,
            "name": "sample.dxf",
            "storage_uri": "gdrive:///AEC-INTELLIGENCE/00_SOURCES/objects/sha256/aa/" + "a" * 64,
            "content_hash": "sha256:" + "a" * 64,
            "mime_type": "image/vnd.dxf",
            "byte_size": 123,
            "provider": "google_drive",
            "properties": {"kind": "cad-source"},
        }
        created = c.post("/api/v1/artifacts", json=payload)
        assert created.status_code == 201, created.text
        artifact_id = created.json()["id"]

        fetched = c.get(f"/api/v1/artifacts/{artifact_id}")
        assert fetched.status_code == 200
        assert fetched.json()["content_hash"] == payload["content_hash"]

        listed = c.get("/api/v1/artifacts")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        duplicate = c.post("/api/v1/artifacts", json=payload)
        assert duplicate.status_code == 409


class FakeAecAdapter:
    enabled = True

    def __init__(self):
        self.calls = []

    def query_global_memory(self, question, *, top_k=10, project_id=None):
        self.calls.append((question, top_k, project_id))
        return {
            "route": "GLOBAL_MEMORY",
            "query": question,
            "hits": [{"project_id": project_id or "P1", "object_id": "aec://object/door-1", "score": 0.9}],
        }


def test_aec_federation_status_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SION_AEC_ONTOLOGY_ROOT", raising=False)
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app) as c:
        status = c.get("/api/v1/aec/status")
        assert status.status_code == 200
        assert status.json() == {
            "status": "disabled",
            "enabled": False,
            "mode": "read_only_federation",
            "source": "khs0927/Ontology",
            "canonical": False,
        }

        query = c.get("/api/v1/aec/query", params={"question": "door"})
        assert query.status_code == 503


def test_aec_federation_query_is_read_only_and_advisory():
    adapter = FakeAecAdapter()
    app = create_app(database_url="sqlite://", auto_create_schema=True, aec_adapter=adapter)
    with TestClient(app) as c:
        response = c.get(
            "/api/v1/aec/query",
            params={"question": "door near lobby", "top_k": 4, "project_id": "P-AEC"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "khs0927/Ontology"
        assert body["canonical"] is False
        assert body["read_only"] is True
        assert body["result"]["route"] == "GLOBAL_MEMORY"
        assert adapter.calls == [("door near lobby", 4, "P-AEC")]


def test_project_contract_catalog_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SION_PROJECT_CONTRACTS_PATH", raising=False)
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app) as c:
        status = c.get("/api/v1/contracts/status")
        assert status.status_code == 200
        assert status.json()["configured"] is False
        assert status.json()["mode"] == "read_only_catalog"
        result = c.get("/api/v1/contracts")
        assert result.status_code == 503


def test_project_contract_catalog_filters_without_mutation(tmp_path):
    registry = tmp_path / "integration.contracts.json"
    registry.write_text(
        json.dumps(
            {
                "project_contracts": [
                    {
                        "id": "aec-source-to-cad-executor",
                        "schema": "aec-executor-handoff/1",
                        "producer": "khs0927/Ontology",
                        "consumers": ["khs0927/power-cad-mcp", "khs0927/All-In-Cad"],
                        "verified_consumers": ["khs0927/power-cad-mcp", "khs0927/All-In-Cad"],
                        "pending_consumers": [],
                        "purpose": "test",
                        "invariants": ["execution_authorized=false"],
                        "verification": {
                            "status": "verified_in_ci",
                            "scope": "test fixture",
                            "evidence": ["https://example.invalid/ci/1"],
                            "real_cad_e2e": False,
                        },
                    },
                    {
                        "id": "cad-drawing-grammar",
                        "schema": "cad-drawing-grammar/1",
                        "producer": "khs0927/HS-CAD",
                        "consumers": ["khs0927/power-cad-mcp"],
                        "verified_consumers": [],
                        "pending_consumers": ["khs0927/power-cad-mcp"],
                        "purpose": "test",
                        "invariants": ["read-only"],
                        "verification": {
                            "status": "producer_verified_consumer_pending",
                            "scope": "test fixture",
                            "evidence": ["https://example.invalid/ci/2"],
                            "real_cad_e2e": False,
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog = ProjectContractCatalog(registry)
    app = create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        project_contract_catalog=catalog,
    )
    with TestClient(app) as c:
        status = c.get("/api/v1/contracts/status")
        assert status.status_code == 200
        assert status.json()["enabled"] is True

        by_consumer = c.get(
            "/api/v1/contracts",
            params={"consumer": "khs0927/power-cad-mcp"},
        )
        assert by_consumer.status_code == 200
        assert by_consumer.json()["count"] == 2
        assert by_consumer.json()["read_only"] is True

        by_schema = c.get(
            "/api/v1/contracts",
            params={"schema": "aec-executor-handoff/1"},
        )
        assert by_schema.status_code == 200
        assert by_schema.json()["count"] == 1
        assert by_schema.json()["contracts"][0]["producer"] == "khs0927/Ontology"

        verified = c.get(
            "/api/v1/contracts",
            params={"verification_status": "verified_in_ci"},
        )
        assert verified.status_code == 200
        assert verified.json()["count"] == 1
        assert verified.json()["contracts"][0]["id"] == "aec-source-to-cad-executor"

        pending = c.get(
            "/api/v1/contracts",
            params={"verification_status": "producer_verified_consumer_pending"},
        )
        assert pending.status_code == 200
        assert pending.json()["count"] == 1
        assert pending.json()["contracts"][0]["id"] == "cad-drawing-grammar"


def test_project_contract_catalog_rejects_unclassified_consumers(tmp_path):
    registry = tmp_path / "integration.contracts.json"
    registry.write_text(
        json.dumps(
            {
                "project_contracts": [
                    {
                        "id": "bad-contract",
                        "schema": "bad/1",
                        "producer": "khs0927/source",
                        "consumers": ["khs0927/consumer"],
                        "verified_consumers": [],
                        "pending_consumers": [],
                        "purpose": "invalid fixture",
                        "invariants": ["read-only"],
                        "verification": {
                            "status": "declared",
                            "scope": "test fixture",
                            "evidence": ["https://example.invalid/ci"],
                            "real_cad_e2e": False,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        ProjectContractCatalog(registry).read()
    except Exception as exc:
        assert "verified or pending" in str(exc)
    else:
        raise AssertionError("unclassified consumer must be rejected")


def test_bearer_scope_enforces_least_privilege():
    token = "read-aec-token-1234567890"
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((token, frozenset({"read:aec"})),),
    )
    adapter = FakeAecAdapter()
    app = create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        aec_adapter=adapter,
        auth_policy=policy,
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as c:
        missing = c.get("/api/v1/aec/status")
        assert missing.status_code == 401

        allowed = c.get("/api/v1/aec/status", headers=headers)
        assert allowed.status_code == 200

        denied_read = c.get("/api/v1/entities", headers=headers)
        assert denied_read.status_code == 403
        assert "read:knowledge" in denied_read.json()["detail"]

        denied_write = c.post(
            "/api/v1/entities",
            headers=headers,
            json={
                "stable_key": "concept:blocked",
                "entity_type_id": "Concept",
                "name": "Blocked",
                "properties": {},
            },
        )
        assert denied_write.status_code == 403
        assert "write:knowledge" in denied_write.json()["detail"]


def test_bearer_wildcard_token_can_read_and_write_knowledge():
    token = "admin-token-123456789012"
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((token, frozenset({"*"})),),
    )
    app = create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        auth_policy=policy,
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as c:
        created = c.post(
            "/api/v1/entities",
            headers=headers,
            json={
                "stable_key": "concept:authorized",
                "entity_type_id": "Concept",
                "name": "Authorized",
                "properties": {},
            },
        )
        assert created.status_code == 201, created.text
        listed = c.get("/api/v1/entities", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()) == 1


def test_temporal_relations_support_history_current_view_and_invalidation():
    with client() as c:
        source = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "project:temporal",
                "entity_type_id": "Project",
                "name": "Temporal Project",
                "properties": {},
            },
        )
        target = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "tool:temporal",
                "entity_type_id": "Tool",
                "name": "Temporal Tool",
                "properties": {},
            },
        )
        assert source.status_code == 201
        assert target.status_code == 201

        created = c.post(
            "/api/v1/relations",
            json={
                "stable_key": "project:temporal:USES:tool:temporal:v1",
                "source_entity_id": source.json()["id"],
                "target_entity_id": target.json()["id"],
                "relation_type_id": "USES",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "properties": {},
            },
        )
        assert created.status_code == 201, created.text
        relation_id = created.json()["id"]

        before = c.get(
            "/api/v1/relations",
            params={"at": "2025-12-31T23:59:59+00:00"},
        )
        assert before.status_code == 200
        assert before.json() == []

        during = c.get(
            "/api/v1/relations",
            params={"at": "2026-01-15T00:00:00+00:00"},
        )
        assert during.status_code == 200
        assert [row["id"] for row in during.json()] == [relation_id]

        invalidated = c.post(
            f"/api/v1/relations/{relation_id}/invalidate",
            json={
                "valid_to": "2026-02-01T00:00:00+00:00",
                "reason": "superseded by design revision",
            },
        )
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["properties"]["temporal"]["reason"] == "superseded by design revision"

        historical = c.get(
            "/api/v1/relations",
            params={"at": "2026-01-31T23:59:59+00:00"},
        )
        assert len(historical.json()) == 1

        boundary = c.get(
            "/api/v1/relations",
            params={"at": "2026-02-01T00:00:00+00:00"},
        )
        assert boundary.json() == []

        current = c.get("/api/v1/relations", params={"active_only": "true"})
        assert current.status_code == 200
        assert current.json() == []

        historical_graph = c.get(
            "/api/v1/graph",
            params={"at": "2026-01-15T00:00:00+00:00"},
        )
        assert historical_graph.status_code == 200
        assert historical_graph.json()["edge_count"] == 1
        assert historical_graph.json()["edges"][0]["valid_from"] is not None
        assert historical_graph.json()["edges"][0]["valid_to"] is not None

        current_graph = c.get("/api/v1/graph", params={"active_only": "true"})
        assert current_graph.status_code == 200
        assert current_graph.json()["edge_count"] == 0

        repeated = c.post(
            f"/api/v1/relations/{relation_id}/invalidate",
            json={"valid_to": "2026-03-01T00:00:00+00:00"},
        )
        assert repeated.status_code == 409


def test_temporal_invalidation_rejects_time_before_valid_from():
    with client() as c:
        source = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "concept:temporal-source",
                "entity_type_id": "Concept",
                "name": "Source",
                "properties": {},
            },
        )
        target = c.post(
            "/api/v1/entities",
            json={
                "stable_key": "concept:temporal-target",
                "entity_type_id": "Concept",
                "name": "Target",
                "properties": {},
            },
        )
        created = c.post(
            "/api/v1/relations",
            json={
                "stable_key": "temporal:future",
                "source_entity_id": source.json()["id"],
                "target_entity_id": target.json()["id"],
                "relation_type_id": "RELATED_TO",
                "valid_from": "2026-05-01T00:00:00+00:00",
                "properties": {},
            },
        )
        assert created.status_code == 201
        rejected = c.post(
            f"/api/v1/relations/{created.json()['id']}/invalidate",
            json={"valid_to": "2026-04-01T00:00:00+00:00"},
        )
        assert rejected.status_code == 409
