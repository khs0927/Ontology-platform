from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sion_api.main import create_app
from sion_graphrag import GraphRagConfig, build_custom_kg


def _seed(c: TestClient) -> None:
    wall = c.post(
        "/api/v1/entities",
        json={
            "stable_key": "aec:wall:w1",
            "entity_type_id": "Project",
            "name": "Exterior Wall W1",
            "description": "200 mm reinforced concrete wall",
            "properties": {"thickness_mm": 200},
        },
    )
    assert wall.status_code == 201, wall.text
    door = c.post(
        "/api/v1/entities",
        json={"stable_key": "aec:door:d1", "entity_type_id": "Project", "name": "Main Door D1", "properties": {}},
    )
    assert door.status_code == 201, door.text
    relation = c.post(
        "/api/v1/relations",
        json={
            "stable_key": "aec:door:d1|RELATED_TO|aec:wall:w1",
            "source_entity_id": door.json()["id"],
            "target_entity_id": wall.json()["id"],
            "relation_type_id": "RELATED_TO",
            "confidence": 0.9,
        },
    )
    assert relation.status_code == 201, relation.text
    evidence = c.post(
        "/api/v1/evidence",
        json={
            "relation_id": relation.json()["id"],
            "source_uri": "gdrive://AEC-INTELLIGENCE/plan-A101.dwg",
            "source_locator": "handle:2F1",
                    },
    )
    assert evidence.status_code == 201, evidence.text


def test_custom_kg_carries_stable_keys_and_evidence():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app) as c:
        _seed(c)
        with app.state.session_factory() as session:
            kg = build_custom_kg(session)

    assert {e["entity_name"] for e in kg["entities"]} == {"aec:wall:w1", "aec:door:d1"}
    [rel] = kg["relationships"]
    assert (rel["src_id"], rel["tgt_id"]) == ("aec:door:d1", "aec:wall:w1")
    assert rel["weight"] == pytest.approx(1.9)
    assert "gdrive://AEC-INTELLIGENCE/plan-A101.dwg @ handle:2F1" in rel["description"]
    aliases = {chunk["source_id"] for chunk in kg["chunks"]}
    assert rel["source_id"] in aliases
    assert all(entity["source_id"] in aliases for entity in kg["entities"])


def test_config_requires_embedding_model(monkeypatch):
    monkeypatch.delenv("SION_GRAPHRAG_EMBED_MODEL", raising=False)
    assert GraphRagConfig.from_env() is None
    monkeypatch.setenv("SION_GRAPHRAG_EMBED_MODEL", "bge-m3")
    monkeypatch.setenv("SION_GRAPHRAG_EMBED_DIM", "1024")
    config = GraphRagConfig.from_env()
    assert config.storage == "postgres" and config.embedding_dim == 1024 and not config.answers_enabled


def test_graphrag_endpoints_report_unconfigured(monkeypatch):
    monkeypatch.delenv("SION_GRAPHRAG_EMBED_MODEL", raising=False)
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app) as c:
        assert c.get("/api/v1/graphrag/status").json()["configured"] is False
        assert c.post("/api/v1/graphrag/query", json={"question": "door"}).status_code == 503


def test_lightrag_round_trip_on_local_storage(tmp_path: Path):
    pytest.importorskip("lightrag")
    import numpy as np
    from lightrag.utils import Tokenizer

    from sion_graphrag import SionGraphRag

    class CharTokenizer:
        def encode(self, content: str) -> list[int]:
            return [ord(ch) for ch in content]

        def decode(self, tokens: list[int]) -> str:
            return "".join(chr(t) for t in tokens)

    async def embed(texts: list[str]):
        vectors = np.zeros((len(texts), 64))
        for row, text in enumerate(texts):
            for word in text.lower().split():
                vectors[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)

    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app) as c:
        _seed(c)

    config = GraphRagConfig(
        workspace="test",
        storage="local",
        working_dir=tmp_path,
        embedding_model="hash-64",
        embedding_dim=64,
    )
    engine = SionGraphRag(config, embedding_func=embed, tokenizer=Tokenizer("chars", CharTokenizer()))

    async def run():
        try:
            written = await engine.project(app.state.session_factory)
            result = await engine.query("Main Door D1 Exterior Wall W1", mode="mix")
        finally:
            await engine.close()
        return written, result

    written, result = asyncio.run(run())
    assert written == {"chunks": 3, "entities": 2, "relationships": 1}
    assert "context" in result
    assert "aec:door:d1" in result["context"]
