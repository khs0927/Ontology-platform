"""Issue #80: the default GraphRAG projection never feeds /review-rejected relations."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sion_api import models
from sion_api.main import create_app
from sion_graphrag import GraphRagConfig, SionGraphRag
from sqlalchemy import select

STATES = {"a|RELATED_TO|hv": "human_verified", "a|RELATED_TO|un": "unverified", "a|RELATED_TO|rj": "rejected"}


class _FakeRag:
    def __init__(self) -> None:
        self.inserted: list[dict] = []

    async def ainsert_custom_kg(self, custom_kg, full_doc_id=None):
        self.inserted.append(custom_kg)


class _Engine(SionGraphRag):
    async def start(self) -> None:  # no LightRAG needed: capture what would be written
        if self._rag is None:
            self._rag = _FakeRag()


def _app():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        ids = {}
        for key in ("a", "hv", "un", "rj"):
            r = c.post("/api/v1/entities", json={"stable_key": key, "entity_type_id": "Project", "name": key})
            assert r.status_code == 201, r.text
            ids[key] = r.json()["id"]
        for stable_key in STATES:
            r = c.post("/api/v1/relations", json={
                "stable_key": stable_key, "source_entity_id": ids["a"],
                "target_entity_id": ids[stable_key.rsplit("|", 1)[1]], "relation_type_id": "RELATED_TO",
            })
            assert r.status_code == 201, r.text
    with app.state.session_factory() as session:
        for rel in session.scalars(select(models.Relation)):
            rel.verification_state = STATES[rel.stable_key]
        session.commit()
    return app


def _engine(tmp_path: Path) -> _Engine:
    return _Engine(GraphRagConfig(workspace="t", storage="local", working_dir=tmp_path,
                                  embedding_model="none", embedding_dim=8))


def _targets(engine: _Engine) -> set[str]:
    return {r["tgt_id"] for r in engine._rag.inserted[-1]["relationships"]}


def test_default_projection_excludes_rejected(tmp_path):
    app, engine = _app(), _engine(tmp_path)
    written = asyncio.run(engine.project(app.state.session_factory))
    assert _targets(engine) == {"hv", "un"}
    assert written["relationships"] == 2
    chunks = {c["source_id"] for c in engine._rag.inserted[-1]["chunks"]}
    assert "sion:relation:a|RELATED_TO|rj" not in chunks


def test_audit_projection_includes_rejected(tmp_path):
    app, engine = _app(), _engine(tmp_path)
    asyncio.run(engine.project(app.state.session_factory, include_rejected=True))
    assert _targets(engine) == {"hv", "un", "rj"}


def test_project_endpoint_default_and_audit_flag(tmp_path):
    engine = _engine(tmp_path)
    app = create_app(database_url="sqlite://", auto_create_schema=True, graphrag=engine)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        body = c.post("/api/v1/graphrag/project").json()
        assert body["include_rejected"] is False
        body = c.post("/api/v1/graphrag/project", params={"include_rejected": "true"}).json()
        assert body["include_rejected"] is True
