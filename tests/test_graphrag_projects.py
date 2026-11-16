"""GraphRAG per-project workspaces: projection, isolation and the project ACL."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_api import models
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_graphrag import GraphRagConfig, SionGraphRag, build_custom_kg
from sion_graphrag.engine import project_workspace

READ_A = "graphrag-read-a-token-0001"
WRITE_A = "graphrag-write-a-token-0001"
ADMIN = "graphrag-admin-token-0001"


def seed(session_factory) -> tuple[str, str]:
    """Two projects, each with a private wall and door, plus one shared entity."""
    with session_factory() as s:
        ids = []
        for label, material in (("a", "concrete"), ("b", "timber")):
            project = models.Entity(stable_key=f"proj:{label}", entity_type_id="Project", name=f"Project {label.upper()}")
            s.add(project)
            s.flush()
            pid = str(project.id)
            wall = models.Entity(
                stable_key=f"{label}:wall",
                entity_type_id="Project",
                name=f"Wall {label.upper()}",
                description=f"{material} wall",
                properties={"project_id": pid},
            )
            door = models.Entity(
                stable_key=f"{label}:door", entity_type_id="Project", name=f"Door {label.upper()}", properties={"project_id": pid}
            )
            s.add_all([wall, door])
            s.flush()
            s.add(models.Relation(
                stable_key=f"{label}:door|RELATED_TO|{label}:wall",
                source_entity_id=door.id,
                target_entity_id=wall.id,
                relation_type_id="RELATED_TO",
                verification_state="human_verified",
            ))
            ids.append(pid)
        shared = models.Entity(stable_key="shared:code", entity_type_id="Project", name="Building code")
        s.add(shared)
        s.commit()
    return ids[0], ids[1]


def test_project_workspace_name_is_stable_and_validated():
    pid = uuid.uuid4()
    assert project_workspace("sion", pid) == f"sion_p_{pid.hex}"
    assert project_workspace("sion", str(pid).upper()) == f"sion_p_{pid.hex}"
    with pytest.raises(ValueError):
        project_workspace("sion", "../other")
    with pytest.raises(ValueError):
        project_workspace("bad-name", pid)


def test_custom_kg_for_one_project_excludes_other_projects_and_shared():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    project_a, _ = seed(app.state.session_factory)
    with app.state.session_factory() as session:
        kg = build_custom_kg(session, review_states=("verified",), project_id=project_a)
        everything = build_custom_kg(session)
    assert {e["entity_name"] for e in kg["entities"]} == {"proj:a", "a:wall", "a:door"}
    assert [r["src_id"] for r in kg["relationships"]] == ["a:door"]
    assert len(everything["entities"]) == 7


def _engine(tmp_path: Path) -> SionGraphRag:
    pytest.importorskip("lightrag")
    import numpy as np
    from lightrag.utils import Tokenizer

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

    config = GraphRagConfig(
        workspace="test", storage="local", working_dir=tmp_path, embedding_model="hash-64", embedding_dim=64
    )
    return SionGraphRag(config, embedding_func=embed, tokenizer=Tokenizer("chars", CharTokenizer()))


def test_project_engines_keep_separate_lightrag_workspaces(tmp_path: Path):
    engine = _engine(tmp_path)
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    project_a, project_b = seed(app.state.session_factory)

    async def run():
        try:
            a = await engine.for_project(project_a)
            b = await engine.for_project(project_b)
            assert a is await engine.for_project(project_a)
            written_a = await a.project(app.state.session_factory)
            written_b = await b.project(app.state.session_factory)
            hit_a = await a.query("Wall concrete timber Door", mode="mix")
            hit_b = await b.query("Wall concrete timber Door", mode="mix")
        finally:
            await engine.close()
        return written_a, written_b, hit_a, hit_b

    written_a, written_b, hit_a, hit_b = asyncio.run(run())
    assert written_a == {"chunks": 4, "entities": 3, "relationships": 1}
    assert written_b == written_a
    assert "a:wall" in hit_a["context"] and "b:wall" not in hit_a["context"]
    assert "b:wall" in hit_b["context"] and "a:wall" not in hit_b["context"]
    assert "shared:code" not in hit_a["context"]
    workspaces = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert {f"test_p_{uuid.UUID(project_a).hex}", f"test_p_{uuid.UUID(project_b).hex}"} <= workspaces
    assert not engine._children


def test_project_engine_cache_is_bounded(tmp_path: Path):
    engine = _engine(tmp_path)
    engine.max_project_engines = 2

    async def run():
        first = await engine.for_project(uuid.uuid4())
        await engine.for_project(uuid.uuid4())
        await engine.for_project(uuid.uuid4())
        return first

    first = asyncio.run(run())
    assert len(engine._children) == 2
    assert first.config.workspace not in engine._children
    with pytest.raises(RuntimeError):
        asyncio.run(first.for_project(uuid.uuid4()))


class FakeEngine:
    """Records which workspace each route used, without LightRAG."""

    def __init__(self):
        self.config = GraphRagConfig(
            workspace="sion", storage="local", working_dir=Path("."), embedding_model="m", embedding_dim=8
        )
        self.project_id = None
        self.calls: list[tuple[str, str | None]] = []

    async def for_project(self, project_id):
        child = FakeEngine()
        child.calls = self.calls
        child.project_id = str(project_id)
        child.config = GraphRagConfig(
            workspace=project_workspace("sion", project_id), storage="local", working_dir=Path("."),
            embedding_model="m", embedding_dim=8,
        )
        return child

    async def project(self, session_factory, *, include_rejected=False):
        self.calls.append(("project", self.project_id))
        return {"chunks": 0, "entities": 0, "relationships": 0}

    async def query(self, question, *, mode="mix", top_k=20):
        self.calls.append(("query", self.project_id))
        return {"mode": mode, "context": ""}


def bearer_app(project_a: str):
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=(
            (READ_A, frozenset({"read:knowledge", f"project:{project_a}"})),
            (WRITE_A, frozenset({"read:knowledge", "write:knowledge", f"project:{project_a}"})),
            (ADMIN, frozenset({"*"})),
        ),
    )
    engine = FakeEngine()
    app = create_app(database_url="sqlite://", auth_policy=policy, graphrag=engine)
    return app, engine


def test_restricted_callers_only_reach_their_own_project_workspace():
    project_a, project_b = str(uuid.uuid4()), str(uuid.uuid4())
    app, engine = bearer_app(project_a)
    with TestClient(app) as c:
        def post(url, token, **kwargs):
            return c.post(url, headers={"Authorization": f"Bearer {token}"}, **kwargs)

        query = "/api/v1/graphrag/query"
        assert post(query, READ_A, json={"question": "wall"}).status_code == 422
        assert post(query, READ_A, json={"question": "wall", "project_id": project_b}).status_code == 404
        ok = post(query, READ_A, json={"question": "wall", "project_id": project_a})
        assert ok.status_code == 200, ok.text
        assert ok.json()["project_id"] == project_a

        project = "/api/v1/graphrag/project"
        assert post(project, READ_A, params={"project_id": project_a}).status_code == 403
        assert post(project, WRITE_A).status_code == 422
        assert post(project, WRITE_A, params={"project_id": project_b}).status_code == 404
        written = post(project, WRITE_A, params={"project_id": project_a})
        assert written.status_code == 200, written.text
        assert written.json()["workspace"] == f"sion_p_{uuid.UUID(project_a).hex}"

        # Unrestricted callers keep the shared workspace and may also pick a project.
        assert post(query, ADMIN, json={"question": "wall"}).json()["project_id"] is None
        assert post(project, ADMIN, params={"project_id": project_b}).json()["project_id"] == project_b

    assert engine.calls == [
        ("query", project_a),
        ("project", project_a),
        ("query", None),
        ("project", project_b),
    ]
