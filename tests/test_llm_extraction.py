"""Ontology-constrained model extraction (sion_ingestion.llm_extraction): schema, gates, storage."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sion_api import models
from sion_api.db import Base, build_engine, build_session_factory
from sion_api.main import create_app
from sion_api.repository import seed_core_types
from sion_ingestion.llm_extraction import (
    EXTRACTOR,
    LlmConfig,
    OntologySpec,
    chunk_text,
    extract_with_llm,
    grounded,
    response_model,
)
from sqlalchemy import select

CONFIG = LlmConfig(base_url="http://llm.test/v1", model="test-model", api_key="k", chunk_chars=400)
PASSAGE = (
    "# Pipeline\n\nGraphRAG Engine는 PostgreSQL을 사용한다. The review queue validates candidate relations.\n\n"
    "LightRAG depends on pgvector for embeddings."
)


@pytest.fixture
def session(tmp_path):
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with build_session_factory(engine)() as s:
        seed_core_types(s)
        # Database is a kind of Tool here, to exercise subclass-aware domain/range checks
        s.add(models.EntityType(id="Database", label="Database", parent_type_id="Tool"))
        rel = s.get(models.RelationType, "USES")
        rel.source_type_id, rel.target_type_id = "SystemComponent", "Tool"
        for key, name, type_id, aliases in [
            ("sys:graphrag", "GraphRAG Engine", "SystemComponent", []),
            ("tool:postgres", "PostgreSQL", "Database", ["Postgres"]),
            ("tool:lightrag", "LightRAG", "Tool", []),
            ("tool:pgvector", "pgvector", "Tool", []),
            ("wf:review", "review queue", "Workflow", []),
        ]:
            s.add(models.Entity(stable_key=key, name=name, entity_type_id=type_id, properties={"aliases": aliases}))
        s.commit()
        yield s


def reply(relations, entities=()):
    return {"entities": list(entities), "relations": relations}


def transport_for(*replies, seen=None):
    queue = [json.dumps(r) if not isinstance(r, str) else r for r in replies]

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        content = queue.pop(0) if queue else json.dumps(reply([]))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


def write_doc(tmp_path: Path) -> Path:
    path = tmp_path / "pipeline.md"
    path.write_text(PASSAGE, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- schema


def test_reply_schema_enumerates_the_live_ontology(session):
    spec = OntologySpec.from_session(session)
    model = response_model(spec)
    ok = model.model_validate({"entities": [{"name": "LightRAG", "type": "Tool"}],
                               "relations": [{"source": "a", "relation": "USES", "target": "b", "evidence": "a uses b"}]})
    assert ok.relations[0].relation == "USES"
    with pytest.raises(ValidationError):
        model.model_validate(reply([{"source": "a", "relation": "INVENTED", "target": "b", "evidence": "x"}]))
    with pytest.raises(ValidationError):
        model.model_validate({"entities": [{"name": "x", "type": "Spaceship"}], "relations": []})
    assert "EXTRACTED_FROM" not in spec.relations  # importer-only edges are never proposed from prose
    assert spec.is_a("Database", "Tool") and not spec.is_a("Workflow", "Tool")
    assert spec.violation("USES", "SystemComponent", "Database") is None
    assert "needs a SystemComponent source" in spec.violation("USES", "Workflow", "Tool")


def test_grounding_and_chunking():
    assert grounded("PostgreSQL을  사용한다", PASSAGE) and grounded("postgresql을 사용한다", PASSAGE)
    assert not grounded("GraphRAG uses Postgres", PASSAGE)
    chunks = chunk_text("a" * 50 + "\n\n" + "b" * 50 + "\n\n" + "c" * 120, 110)
    assert chunks == ["a" * 50 + "\n\n" + "b" * 50, "c" * 110, "c" * 10]


# --------------------------------------------------------------------------- gates + storage


def test_extraction_gates_and_stores_review_candidates(session, tmp_path):
    seen: list[dict] = []
    model_reply = reply(
        [
            # kept: grounded, both curated, Database is_a Tool satisfies USES range
            {"source": "GraphRAG Engine", "relation": "USES", "target": "PostgreSQL", "evidence": "GraphRAG Engine는 PostgreSQL을 사용한다."},
            # kept: no domain/range declared on DEPENDS_ON
            {"source": "LightRAG", "relation": "DEPENDS_ON", "target": "pgvector", "evidence": "LightRAG depends on pgvector"},
            # dropped: paraphrased evidence
            {"source": "LightRAG", "relation": "USES", "target": "pgvector", "evidence": "LightRAG uses pgvector heavily"},
            # dropped: domain violation (a Workflow cannot USE)
            {"source": "review queue", "relation": "USES", "target": "PostgreSQL", "evidence": "The review queue validates candidate relations."},
            # dropped: endpoint not curated -> entity suggestion
            {"source": "review queue", "relation": "VALIDATES", "target": "candidate relations", "evidence": "The review queue validates candidate relations."},
            # dropped: endpoint name not in the passage
            {"source": "Neo4j", "relation": "RELATED_TO", "target": "LightRAG", "evidence": "LightRAG depends on pgvector"},
        ],
        entities=[{"name": "candidate relations", "type": "Concept"}],
    )
    result = extract_with_llm(session, [write_doc(tmp_path)], CONFIG, transport=transport_for(model_reply, seen=seen))
    assert result["chunks"] == 1 and result["failed_chunks"] == []
    assert result["candidates_created"] == 2 and result["verification_state"] == "unverified"
    reasons = sorted(r["reason"].split(":")[0] for r in result["rejected"])
    assert reasons == ["domain/range", "endpoint is not a curated entity", "endpoint name not in the passage",
                       "evidence is not a quote from the passage"]
    assert result["entity_suggestions"] == [{"name": "candidate relations", "type": "Concept", "evidence": [
        {"source_uri": result["entity_suggestions"][0]["evidence"][0]["source_uri"], "locator": "chunk:0",
         "excerpt": "The review queue validates candidate relations."}]}]

    request = seen[0]
    assert request["model"] == "test-model" and request["temperature"] == 0
    schema = request["response_format"]["json_schema"]
    assert schema["strict"] is True and schema["schema"]["additionalProperties"] is False
    assert "USES" in request["messages"][0]["content"] and "(SystemComponent -> Tool)" in request["messages"][0]["content"]

    rows = {r.relation_type_id: r for r in session.scalars(select(models.Relation))}
    assert set(rows) == {"USES", "DEPENDS_ON"}
    uses = rows["USES"]
    assert uses.verification_state == "unverified" and uses.source_kind == "inferred"
    assert uses.properties["candidate"] is True and uses.properties["extractor"] == EXTRACTOR
    assert uses.properties["model"] == "test-model" and uses.confidence == 0.5
    evidence = session.scalars(select(models.Evidence).where(models.Evidence.relation_id == uses.id)).all()
    assert [e.properties["excerpt"] for e in evidence] == ["GraphRAG Engine는 PostgreSQL을 사용한다."]
    assert evidence[0].source_locator == "chunk:0" and evidence[0].model == "test-model"


def test_schema_error_retries_once_then_reports_the_chunk(session, tmp_path):
    good = reply([{"source": "LightRAG", "relation": "DEPENDS_ON", "target": "pgvector", "evidence": "LightRAG depends on pgvector"}])
    seen: list[dict] = []
    result = extract_with_llm(session, [write_doc(tmp_path)], CONFIG,
                              transport=transport_for('{"entities": [], "relations": [{"relation": "NOPE"}]}', good, seen=seen))
    assert result["candidates_created"] == 1 and len(seen) == 2
    assert "does not match the schema" in seen[1]["messages"][-1]["content"]

    bad = '{"entities": "nope"}'
    result = extract_with_llm(session, [write_doc(tmp_path)], CONFIG, transport=transport_for(bad, bad))
    assert result["candidates_created"] == 0 and "ontology schema" in result["failed_chunks"][0]["reason"]


def test_endpoint_failure_is_reported_not_raised(session, tmp_path):
    transport = httpx.MockTransport(lambda r: httpx.Response(500, json={"error": "down"}))
    result = extract_with_llm(session, [write_doc(tmp_path), tmp_path / "missing.md"], CONFIG, transport=transport)
    assert "model endpoint failed" in result["failed_chunks"][0]["reason"]
    assert result["skipped_files"] == [{"path": str(tmp_path / "missing.md"), "reason": "not a file"}]


# --------------------------------------------------------------------------- API


def test_api_requires_configuration_and_exposes_the_schema(tmp_path, monkeypatch):
    monkeypatch.delenv("SION_EXTRACT_BASE_URL", raising=False)
    monkeypatch.delenv("SION_EXTRACT_MODEL", raising=False)
    app = create_app(database_url="sqlite://", auto_create_schema=True, ingest_roots=[tmp_path])
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        r = c.post("/api/v1/extract/relations/llm", json={"paths": [str(write_doc(tmp_path))]})
        assert r.status_code == 503 and "SION_EXTRACT_BASE_URL" in r.json()["detail"]
        schema = c.get("/api/v1/extract/llm/schema").json()
        assert schema["configured"] is False
        relation_enum = schema["schema"]["$defs"]["Triple"]["properties"]["relation"]["enum"]
        assert "USES" in relation_enum and "EXTRACTED_FROM" not in relation_enum
