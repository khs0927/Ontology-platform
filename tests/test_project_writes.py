"""Project-restricted callers writing into their own projects (sion_api.project_writes)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app

ADMIN = "writes-test-admin-token-0001"
WRITER = "writes-test-writer-token-0002"
READER = "writes-test-reader-token-0003"

MARKDOWN = "# 안전관리계획\n\n## 가설구조물 점검\n\n본문 내용.\n".encode("utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SION_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("SION_UPLOAD_MAX_BYTES", "4096")
    url = f"sqlite:///{tmp_path / 'w.db'}"
    admin = {"Authorization": f"Bearer {ADMIN}"}
    seed = AuthPolicy(mode="bearer", token_scopes=((ADMIN, frozenset({"*"})),))
    ids: dict[str, str] = {}
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=seed)) as client:
        for name in ("a", "b"):
            ids[name] = client.post(
                "/api/v1/entities",
                json={"stable_key": f"proj-{name}", "entity_type_id": "Project", "name": f"project {name}"},
                headers=admin,
            ).json()["id"]
            for i in (1, 2):
                ids[f"{name}{i}"] = client.post(
                    "/api/v1/entities",
                    json={
                        "stable_key": f"doc-{name}{i}",
                        "entity_type_id": "Document",
                        "name": f"{name} doc {i}",
                        "properties": {"project_id": ids[name], "keep": "yes", "drop": "me"},
                    },
                    headers=admin,
                ).json()["id"]
        ids["rel_b"] = client.post(
            "/api/v1/relations",
            json={"stable_key": "rel-b", "source_entity_id": ids["b1"], "target_entity_id": ids["b2"],
                  "relation_type_id": "RELATED_TO"},
            headers=admin,
        ).json()["id"]
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=(
            (ADMIN, frozenset({"*"})),
            (WRITER, frozenset({"read:knowledge", "write:knowledge"})),
            (READER, frozenset({"read:knowledge"})),
        ),
        token_projects=((WRITER, frozenset({ids["a"]})), (READER, frozenset({ids["a"]}))),
    )
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=policy)) as client:
        yield client, ids, tmp_path / "uploads"


WRITER_H = {"Authorization": f"Bearer {WRITER}"}
READER_H = {"Authorization": f"Bearer {READER}"}
ADMIN_H = {"Authorization": f"Bearer {ADMIN}"}


def test_entity_and_relation_writes_stay_inside_the_project(env):
    client, ids, _ = env

    def entity(**extra):
        body = {"stable_key": extra.pop("key", "new"), "entity_type_id": "Concept", "name": "n", **extra}
        return client.post("/api/v1/entities", json=body, headers=WRITER_H)

    assert entity().status_code == 422  # project_id is required
    assert entity(properties={"project_id": ids["b"]}).status_code == 404
    project = client.post(
        "/api/v1/entities", json={"stable_key": "p-new", "entity_type_id": "Project", "name": "p"}, headers=WRITER_H
    )
    assert project.status_code == 403
    created = entity(key="mine", properties={"project_id": ids["a"]})
    assert created.status_code == 201, created.text

    def relation(source, target, key):
        return client.post(
            "/api/v1/relations",
            json={"stable_key": key, "source_entity_id": ids[source], "target_entity_id": target or created.json()["id"],
                  "relation_type_id": "RELATED_TO"},
            headers=WRITER_H,
        )

    assert relation("a1", ids["b1"], "cross").status_code == 404
    assert relation("a1", None, "inside").status_code == 201

    invalidate = {"valid_to": "2026-11-13T00:00:00Z", "reason": "test"}
    assert client.post(f"/api/v1/relations/{ids['rel_b']}/invalidate", json=invalidate, headers=WRITER_H).status_code == 404
    evidence = {"source_uri": "urn:test", "entity_id": ids["b1"]}
    assert client.post("/api/v1/evidence", json=evidence, headers=WRITER_H).status_code == 404
    evidence["entity_id"] = ids["a1"]
    assert client.post("/api/v1/evidence", json=evidence, headers=WRITER_H).status_code == 201

    # Read-only members cannot write at all; admins keep writing without a project.
    assert client.post(
        "/api/v1/entities",
        json={"stable_key": "r", "entity_type_id": "Concept", "name": "n", "properties": {"project_id": ids["a"]}},
        headers=READER_H,
    ).status_code == 403
    assert client.post(
        "/api/v1/entities", json={"stable_key": "free", "entity_type_id": "Concept", "name": "n"}, headers=ADMIN_H
    ).status_code == 201


def test_patch_edits_only_visible_entities_and_keeps_the_project(env):
    client, ids, _ = env
    assert client.patch(f"/api/v1/entities/{ids['b1']}", json={"name": "x"}, headers=WRITER_H).status_code == 404

    response = client.patch(
        f"/api/v1/entities/{ids['a1']}",
        json={"name": "renamed", "description": "edited", "properties": {"drop": None, "added": 1}},
        headers=WRITER_H,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "renamed" and body["description"] == "edited"
    assert body["properties"] == {"project_id": ids["a"], "keep": "yes", "added": 1}

    moved = client.patch(f"/api/v1/entities/{ids['a1']}", json={"properties": {"project_id": ids["b"]}}, headers=WRITER_H)
    assert moved.status_code == 403
    unscoped = client.patch(f"/api/v1/entities/{ids['a1']}", json={"properties": {"project_id": None}}, headers=WRITER_H)
    assert unscoped.status_code == 403
    assert client.patch(f"/api/v1/entities/{ids['a1']}", json={"name": None}, headers=WRITER_H).status_code == 422
    assert client.patch(f"/api/v1/entities/{ids['a1']}", json={"entity_type_id": "Project"}, headers=WRITER_H).status_code == 422
    assert client.patch(f"/api/v1/entities/{ids['a1']}", json={"name": "r"}, headers=READER_H).status_code == 403


def test_upload_ingests_into_the_project_only(env):
    client, ids, root = env
    url = f"/api/v1/projects/{ids['a']}/documents"

    other = client.post(f"/api/v1/projects/{ids['b']}/documents", params={"filename": "x.md"}, content=MARKDOWN, headers=WRITER_H)
    assert other.status_code == 404
    assert client.post(url, params={"filename": "x.md"}, content=MARKDOWN, headers=READER_H).status_code == 403
    assert client.post(url, params={"filename": "x.exe"}, content=b"MZ", headers=WRITER_H).status_code == 415
    assert client.post(url, params={"filename": "x.md"}, content=b"", headers=WRITER_H).status_code == 422
    assert client.post(url, params={"filename": "x.md"}, content=b"a" * 5000, headers=WRITER_H).status_code == 413
    # A non-project entity id is not a project.
    assert client.post(
        f"/api/v1/projects/{ids['a1']}/documents", params={"filename": "x.md"}, content=MARKDOWN, headers=ADMIN_H
    ).status_code == 404

    first = client.post(url, params={"filename": "../../plan.md"}, content=MARKDOWN, headers=WRITER_H)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["filename"] == "plan.md"
    assert body["created_nodes"] >= 3 and body["document"]["name"] == "안전관리계획"
    assert str(root) not in first.text  # server paths never leave the API
    stored = list(root.rglob("plan.md"))
    assert len(stored) == 1 and stored[0].is_relative_to(root / ids["a"])
    assert not list(root.rglob(".upload-*"))

    again = client.post(url, params={"filename": "plan.md"}, content=MARKDOWN, headers=WRITER_H)
    assert again.status_code == 201
    assert again.json()["created_nodes"] == 0
    assert again.json()["document"]["id"] == body["document"]["id"]

    listed = client.get(url, headers=READER_H).json()["items"]
    assert len(listed) == 3  # the upload plus the two seeded project documents, newest first
    assert listed[0]["id"] == body["document"]["id"]
    assert listed[0]["sha256"] == body["sha256"] and listed[0]["filename"] == "plan.md"
    assert client.get(f"/api/v1/projects/{ids['b']}/documents", headers=READER_H).status_code == 404

    # Every node the upload created is visible to project members and to nobody else.
    visible = {e["name"] for e in client.get("/api/v1/entities", params={"limit": 1000}, headers=READER_H).json()}
    assert {"안전관리계획", "가설구조물 점검"} <= visible
    graph = client.get("/api/v1/graph", params={"project_id": ids["a"]}, headers=READER_H).json()
    assert any(edge["type"] == "EXTRACTED_FROM" for edge in graph["edges"])
