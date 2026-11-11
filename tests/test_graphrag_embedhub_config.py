from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
from sion_graphrag.engine import GraphRagConfig


def test_embed_provider_defaults_to_openai_and_reads_embedhub(monkeypatch, tmp_path):
    monkeypatch.setenv("SION_GRAPHRAG_EMBED_MODEL", "nv-1b")
    monkeypatch.setenv("SION_GRAPHRAG_EMBED_DIM", "1024")
    monkeypatch.setenv("SION_GRAPHRAG_WORKING_DIR", str(tmp_path))
    monkeypatch.delenv("SION_GRAPHRAG_EMBED_PROVIDER", raising=False)
    assert GraphRagConfig.from_env().embedding_provider == "openai"
    monkeypatch.setenv("SION_GRAPHRAG_EMBED_PROVIDER", " EmbedHub ")
    cfg = GraphRagConfig.from_env()
    assert cfg.embedding_provider == "embedhub" and cfg.embedding_model == "nv-1b"
