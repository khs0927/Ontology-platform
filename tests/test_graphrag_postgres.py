"""LightRAG on real PostgreSQL + pgvector: table graph storage and per-project workspaces.

Runs only when SION_TEST_POSTGRES_URL points at a disposable PostgreSQL with pgvector and
LightRAG is installed (CI: verify.yml postgres job). Embeddings are a local hash, so no
model server is needed; the Postgres storages (KV, vector, PGTableGraphStorage, doc
status) are the real ones.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

DSN = os.getenv("SION_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="SION_TEST_POSTGRES_URL not set")


def _lightrag_env(dsn: str) -> dict[str, str]:
    """POSTGRES_* variables LightRAG reads, from a libpq URL (TCP or ?host=/socket/dir)."""
    url = urlparse(dsn)
    query = parse_qs(url.query)
    env = {
        "POSTGRES_HOST": query.get("host", [url.hostname or "localhost"])[0],
        "POSTGRES_PORT": query.get("port", [str(url.port or 5432)])[0],
        "POSTGRES_USER": unquote(url.username or "postgres"),
        "POSTGRES_DATABASE": url.path.lstrip("/") or "postgres",
        # LightRAG requires the variable even for trust/peer auth.
        "POSTGRES_PASSWORD": unquote(url.password or ""),
    }
    return env


def _seed(session_factory) -> tuple[str, str]:
    from sion_api import models

    suffix = uuid.uuid4().hex[:8]  # the database is shared with other Postgres tests
    with session_factory() as s:
        ids = []
        for label, material in (("a", "concrete"), ("b", "timber")):
            project = models.Entity(
                stable_key=f"it-{suffix}:proj:{label}", entity_type_id="Project", name=f"Project {label.upper()}"
            )
            s.add(project)
            s.flush()
            pid = str(project.id)
            wall = models.Entity(
                stable_key=f"it-{suffix}:{label}:wall", entity_type_id="Project", name=f"Wall {label.upper()}",
                description=f"{material} wall", properties={"project_id": pid},
            )
            door = models.Entity(
                stable_key=f"it-{suffix}:{label}:door", entity_type_id="Project", name=f"Door {label.upper()}",
                properties={"project_id": pid},
            )
            s.add_all([wall, door])
            s.flush()
            s.add(models.Relation(
                stable_key=f"it-{suffix}:{label}:door|RELATED_TO|wall",
                source_entity_id=door.id, target_entity_id=wall.id,
                relation_type_id="RELATED_TO", verification_state="human_verified",
            ))
            ids.append(pid)
        s.commit()
    return ids[0], ids[1]


def test_lightrag_postgres_project_workspaces(monkeypatch, tmp_path: Path):
    pytest.importorskip("lightrag")
    pytest.importorskip("asyncpg")
    import asyncpg
    import numpy as np
    from lightrag.utils import Tokenizer
    from sion_api import migrate
    from sion_api.main import create_app
    from sion_graphrag import GraphRagConfig, SionGraphRag

    for key, value in _lightrag_env(DSN).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("POSTGRES_WORKSPACE", raising=False)
    migrate.apply_core(DSN)
    app = create_app(database_url=DSN.replace("postgresql://", "postgresql+psycopg://", 1))
    project_a, project_b = _seed(app.state.session_factory)

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

    base = f"it_{uuid.uuid4().hex[:8]}"
    config = GraphRagConfig(
        workspace=base, storage="postgres", working_dir=tmp_path, embedding_model="hash-64", embedding_dim=64
    )
    assert config.storages["graph_storage"] == "PGTableGraphStorage"
    engine = SionGraphRag(config, embedding_func=embed, tokenizer=Tokenizer("chars", CharTokenizer()))

    async def run():
        try:
            a = await engine.for_project(project_a)
            b = await engine.for_project(project_b)
            written = (await a.project(app.state.session_factory), await b.project(app.state.session_factory))
            hits = (
                await a.query("Wall concrete timber Door", mode="mix"),
                await b.query("Wall concrete timber Door", mode="mix"),
            )
            # Closing one project engine must not break another that shares LightRAG's pool.
            engine.max_project_engines = 1
            await engine.for_project(uuid.uuid4())
            still = await (await engine.for_project(project_b)).query("Wall timber", mode="local")
        finally:
            await engine.close()
        conn = await asyncpg.connect(**_asyncpg_kwargs())
        try:
            # Counts per workspace from LightRAG's own chunk table and the PGTableGraphStorage tables.
            workspaces = {}
            for table in ("lightrag_doc_chunks", "lightrag_graph_nodes", "lightrag_graph_edges"):
                rows = await conn.fetch(
                    f"SELECT workspace, count(*) FROM {table} WHERE workspace LIKE $1 GROUP BY workspace", base + "%"
                )
                for workspace, count in rows:
                    workspaces.setdefault(workspace, {})[table] = count
        finally:
            await conn.close()
        return written, hits, still, workspaces

    written, (hit_a, hit_b), still, workspaces = asyncio.run(run())
    assert written[0] == written[1] == {"chunks": 4, "entities": 3, "relationships": 1}
    assert ":a:wall" in hit_a["context"] and ":b:wall" not in hit_a["context"]
    assert ":b:wall" in hit_b["context"] and ":a:wall" not in hit_b["context"]
    assert ":b:wall" in still["context"]
    expected = {"lightrag_doc_chunks": 4, "lightrag_graph_nodes": 3, "lightrag_graph_edges": 1}
    assert workspaces == {
        f"{base}_p_{uuid.UUID(project_a).hex}": expected,
        f"{base}_p_{uuid.UUID(project_b).hex}": expected,
    }


def _asyncpg_kwargs() -> dict[str, object]:
    env = _lightrag_env(DSN)
    kwargs: dict[str, object] = {
        "host": env["POSTGRES_HOST"],
        "port": int(env["POSTGRES_PORT"]),
        "user": env["POSTGRES_USER"],
        "database": env["POSTGRES_DATABASE"],
    }
    if env["POSTGRES_PASSWORD"]:
        kwargs["password"] = env["POSTGRES_PASSWORD"]
    return kwargs


def test_postgres_workspace_override_is_refused(monkeypatch, tmp_path: Path):
    from sion_graphrag import GraphRagConfig, GraphRagUnavailable, SionGraphRag

    monkeypatch.setenv("POSTGRES_WORKSPACE", "shared")
    config = GraphRagConfig(
        workspace="sion", storage="postgres", working_dir=tmp_path, embedding_model="m", embedding_dim=8
    )
    with pytest.raises(GraphRagUnavailable):
        asyncio.run(SionGraphRag(config).for_project(uuid.uuid4()))
