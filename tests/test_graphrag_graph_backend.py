"""LightRAG graph backend: plain Postgres tables by default, AGE only on request."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
from sion_graphrag.engine import LOCAL_STORAGES, GraphRagConfig


def _env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SION_GRAPHRAG_EMBED_MODEL", "m")
    monkeypatch.setenv("SION_GRAPHRAG_EMBED_DIM", "8")
    monkeypatch.setenv("SION_GRAPHRAG_WORKING_DIR", str(tmp_path))
    monkeypatch.delenv("SION_GRAPHRAG_STORAGE", raising=False)
    monkeypatch.delenv("SION_GRAPHRAG_GRAPH_BACKEND", raising=False)


def test_postgres_defaults_to_table_graph_storage_without_age(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    config = GraphRagConfig.from_env()
    assert config.storage == "postgres" and config.graph_backend == "table"
    storages = config.storages
    assert storages["graph_storage"] == "PGTableGraphStorage"
    assert storages["kv_storage"] == "PGKVStorage" and storages["vector_storage"] == "PGVectorStorage"
    assert "PGGraphStorage" not in storages.values()


def test_age_backend_is_opt_in(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("SION_GRAPHRAG_GRAPH_BACKEND", " AGE ")
    assert GraphRagConfig.from_env().storages["graph_storage"] == "PGGraphStorage"


def test_unknown_graph_backend_is_rejected(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("SION_GRAPHRAG_GRAPH_BACKEND", "neo4j")
    with pytest.raises(ValueError, match="SION_GRAPHRAG_GRAPH_BACKEND"):
        GraphRagConfig.from_env()


def test_local_storage_ignores_graph_backend(tmp_path):
    config = GraphRagConfig(workspace="t", storage="local", working_dir=tmp_path,
                            embedding_model="m", embedding_dim=8, graph_backend="age")
    assert config.storages == LOCAL_STORAGES


def test_pinned_lightrag_ships_table_graph_storage():
    kg = pytest.importorskip("lightrag.kg")
    assert "PGTableGraphStorage" in kg.STORAGE_IMPLEMENTATIONS["GRAPH_STORAGE"]["implementations"]
