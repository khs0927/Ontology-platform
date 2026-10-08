"""POST /v1/search 'model' (power-cad-mcp ontology_search embedding-model hint). No PostgreSQL needed."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aec_intelligence.operational import api as api_module
from aec_intelligence.operational.config import Settings


class FakeDatabase:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def connect(self):
        raise RuntimeError("db reached")
        yield


class FakeResult:
    def __init__(self, kwargs):
        self.kwargs = kwargs

    def to_dict(self):
        return {"hits": [], "query": self.kwargs["query"]}


class FakeRouter:
    calls: list[dict] = []

    def __init__(self, db, settings):
        pass

    def search(self, **kwargs):
        FakeRouter.calls.append(kwargs)
        return FakeResult(kwargs)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api_module, "Database", FakeDatabase)
    monkeypatch.setattr(api_module, "SearchRouter", FakeRouter)
    monkeypatch.delenv("AEC_API_TOKEN", raising=False)
    monkeypatch.delenv("AEC_CORS_ORIGINS", raising=False)
    FakeRouter.calls = []
    settings = Settings(dsn="dummy", data_root=tmp_path / "data", import_roots=(tmp_path.resolve(),))
    assert settings.embedding_model
    return TestClient(api_module.create_app(settings), raise_server_exceptions=False, base_url="http://localhost", client=("127.0.0.1", 50000)), settings


def test_search_without_model_is_unchanged(client):
    c, _ = client
    r = c.post("/v1/search", json={"query": "방화문", "top_k": 5})
    assert r.status_code == 200, r.text
    assert FakeRouter.calls[0]["top_k"] == 5


def test_search_accepts_the_index_embedding_model_case_insensitively(client):
    c, settings = client
    for name in (settings.embedding_model, settings.embedding_model.upper(), f"  {settings.embedding_model} "):
        assert c.post("/v1/search", json={"query": "door", "model": name}).status_code == 200
    assert len(FakeRouter.calls) == 3


def test_search_rejects_a_different_model_with_a_clear_error(client):
    c, settings = client
    r = c.post("/v1/search", json={"query": "door", "model": "text-embedding-3-small"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "text-embedding-3-small" in detail and settings.embedding_model in detail
    assert FakeRouter.calls == []
    assert c.post("/v1/search", json={"query": "door", "model": ""}).status_code == 422
    assert c.post("/v1/search", json={"query": "door", "model": "x" * 201}).status_code == 422
