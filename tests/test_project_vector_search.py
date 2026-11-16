"""Project-restricted callers on pgvector search and embedding writes.

Runs only when SION_TEST_POSTGRES_URL points at a disposable PostgreSQL with pgvector
(CI: verify.yml postgres job). Keys and the model name are unique per run, so the test can
share the database with the other PostgreSQL tests.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

DSN = os.getenv("SION_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="SION_TEST_POSTGRES_URL not set")

ADMIN = "vector-test-admin-token-0001"
MEMBER = "vector-test-member-token-0002"
ADMIN_H = {"Authorization": f"Bearer {ADMIN}"}
MEMBER_H = {"Authorization": f"Bearer {MEMBER}"}


def test_vector_search_and_embedding_writes_stay_inside_the_project():
    import psycopg
    from sion_api import migrate
    from sion_api.auth import AuthPolicy
    from sion_api.main import create_app

    migrate.apply_core(DSN)
    run = uuid.uuid4().hex[:8]
    model = f"test-model-{run}"
    url = DSN.replace("postgresql://", "postgresql+psycopg://", 1)
    seed = AuthPolicy(mode="bearer", token_scopes=((ADMIN, frozenset({"*"})),))
    ids: dict[str, str] = {}
    with TestClient(create_app(database_url=url, auto_create_schema=False, auth_policy=seed)) as client:
        for name in ("a", "b"):
            ids[name] = client.post(
                "/api/v1/entities",
                json={"stable_key": f"vp-{run}-{name}", "entity_type_id": "Project", "name": name},
                headers=ADMIN_H,
            ).json()["id"]
            ids[f"{name}1"] = client.post(
                "/api/v1/entities",
                json={"stable_key": f"ve-{run}-{name}", "entity_type_id": "Document", "name": f"{name} doc",
                      "properties": {"project_id": ids[name]}},
                headers=ADMIN_H,
            ).json()["id"]
    # One chunk per project document, reached through documents.entity_id.
    with psycopg.connect(DSN, autocommit=True) as conn:
        for name in ("a", "b"):
            document = conn.execute(
                "INSERT INTO documents (entity_id, title) VALUES (%s, %s) RETURNING id", (ids[f"{name}1"], name)
            ).fetchone()[0]
            ids[f"{name}_chunk"] = str(
                conn.execute(
                    "INSERT INTO chunks (document_id, ordinal, content) VALUES (%s, 0, %s) RETURNING id",
                    (document, f"{name} chunk"),
                ).fetchone()[0]
            )
        orphan = conn.execute("INSERT INTO documents (title) VALUES ('unscoped') RETURNING id").fetchone()[0]
        ids["orphan_chunk"] = str(
            conn.execute(
                "INSERT INTO chunks (document_id, ordinal, content) VALUES (%s, 0, 'x') RETURNING id", (orphan,)
            ).fetchone()[0]
        )

    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((ADMIN, frozenset({"*"})), (MEMBER, frozenset({"read:knowledge", "write:knowledge"}))),
        token_projects=((MEMBER, frozenset({ids["a"]})),),
    )
    with TestClient(create_app(database_url=url, auto_create_schema=False, auth_policy=policy)) as client:
        def embed(headers, **target):
            return client.post(
                "/api/v1/embeddings", json={"model": model, "embedding": [1.0, 0.0, 0.0], **target}, headers=headers
            )

        assert embed(MEMBER_H, entity_id=ids["b1"]).status_code == 404
        assert embed(MEMBER_H, chunk_id=ids["b_chunk"]).status_code == 404
        assert embed(MEMBER_H, chunk_id=ids["orphan_chunk"]).status_code == 404
        assert embed(MEMBER_H, entity_id=ids["a1"]).status_code == 201
        assert embed(MEMBER_H, chunk_id=ids["a_chunk"]).status_code == 201
        for target in ({"entity_id": ids["b1"]}, {"chunk_id": ids["b_chunk"]}, {"chunk_id": ids["orphan_chunk"]}):
            assert embed(ADMIN_H, **target).status_code == 201

        query = {"model": model, "embedding": [1.0, 0.0, 0.0], "limit": 10}
        member = client.post("/api/v1/vector/search", json=query, headers=MEMBER_H).json()["hits"]
        assert {(h["entity_id"], h["chunk_id"]) for h in member} == {(ids["a1"], None), (None, ids["a_chunk"])}
        assert client.post("/api/v1/vector/search", json=query, headers=ADMIN_H).json()["count"] == 5
        only_b = client.post("/api/v1/vector/search", json={**query, "project_id": ids["b"]}, headers=ADMIN_H).json()
        assert {(h["entity_id"], h["chunk_id"]) for h in only_b["hits"]} == {(ids["b1"], None), (None, ids["b_chunk"])}
        denied = client.post("/api/v1/vector/search", json={**query, "project_id": ids["b"]}, headers=MEMBER_H)
        assert denied.status_code == 404
