"""Project-restricted callers (OIDC users, project tokens) on the knowledge read routes."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app

ADMIN = "tenancy-test-admin-token-0001"
LIMITED = "tenancy-test-limited-token-0002"


def _seed(client, admin):
    ids = {}
    for name in ("a", "b"):
        project = client.post(
            "/api/v1/entities",
            json={"stable_key": f"proj-{name}", "entity_type_id": "Project", "name": f"project {name}"},
            headers=admin,
        ).json()
        ids[name] = project["id"]
        for i in (1, 2):
            ids[f"{name}{i}"] = client.post(
                "/api/v1/entities",
                json={
                    "stable_key": f"doc-{name}{i}",
                    "entity_type_id": "Document",
                    "name": f"{name} doc {i}",
                    "properties": {"project_id": project["id"]},
                },
                headers=admin,
            ).json()["id"]
    ids["shared"] = client.post(
        "/api/v1/entities",
        json={"stable_key": "law-x", "entity_type_id": "Document", "name": "unscoped"},
        headers=admin,
    ).json()["id"]
    for source, target in (("a1", "a2"), ("b1", "b2"), ("a1", "b1")):
        response = client.post(
            "/api/v1/relations",
            json={"stable_key": f"rel-{source}-{target}", "source_entity_id": ids[source],
                  "target_entity_id": ids[target], "relation_type_id": "RELATED_TO"},
            headers=admin,
        )
        assert response.status_code == 201, response.text
    return ids


def test_restricted_caller_sees_only_its_project(tmp_path):
    url = f"sqlite:///{tmp_path / 't.db'}"
    admin = {"Authorization": f"Bearer {ADMIN}"}
    seed_policy = AuthPolicy(mode="bearer", token_scopes=((ADMIN, frozenset({"*"})),))
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=seed_policy)) as client:
        ids = _seed(client, admin)

    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((ADMIN, frozenset({"*"})), (LIMITED, frozenset({"read:knowledge"}))),
        token_projects=((LIMITED, frozenset({ids["a"]})),),
    )
    limited = {"Authorization": f"Bearer {LIMITED}"}
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=policy)) as client:
        names = {e["name"] for e in client.get("/api/v1/entities", headers=limited).json()}
        assert names == {"project a", "a doc 1", "a doc 2"}
        assert len(client.get("/api/v1/entities", headers=admin).json()) == 7

        assert client.get(f"/api/v1/entities/{ids['a1']}", headers=limited).status_code == 200
        for hidden in ("b1", "b", "shared"):
            assert client.get(f"/api/v1/entities/{ids[hidden]}", headers=limited).status_code == 404

        # The a1 -> b1 edge crosses projects, so it is hidden from the restricted caller.
        relations = client.get("/api/v1/relations", headers=limited).json()
        assert [(r["source_entity_id"], r["target_entity_id"]) for r in relations] == [(ids["a1"], ids["a2"])]
        graph = client.get("/api/v1/graph", headers=limited).json()
        assert {n["id"] for n in graph["nodes"]} == {ids["a"], ids["a1"], ids["a2"]}
        assert len(graph["edges"]) == 1

        # project_id narrows for everyone; another tenant's project answers 404, not an empty list.
        assert len(client.get(f"/api/v1/entities?project_id={ids['b']}", headers=admin).json()) == 3
        assert len(client.get(f"/api/v1/graph?project_id={ids['b']}", headers=admin).json()["edges"]) == 1
        assert client.get(f"/api/v1/entities?project_id={ids['b']}", headers=limited).status_code == 404
        assert client.get(f"/api/v1/graph?project_id={uuid.uuid4()}", headers=limited).status_code == 404

        # Shared reference data stays readable; other cross-project routes stay closed.
        assert client.get("/api/v1/law/search?q=건축", headers=limited).status_code == 200
        assert client.get("/api/v1/artifacts", headers=limited).status_code == 403


def test_caller_with_no_projects_sees_nothing(tmp_path):
    url = f"sqlite:///{tmp_path / 't.db'}"
    admin = {"Authorization": f"Bearer {ADMIN}"}
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((ADMIN, frozenset({"*"})), (LIMITED, frozenset({"read:knowledge"}))),
        token_projects=((LIMITED, frozenset()),),
    )
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=policy)) as client:
        _seed(client, admin)
        limited = {"Authorization": f"Bearer {LIMITED}"}
        assert client.get("/api/v1/entities", headers=limited).json() == []
        assert client.get("/api/v1/relations", headers=limited).json() == []
        graph = client.get("/api/v1/graph", headers=limited).json()
        assert graph["nodes"] == [] and graph["edges"] == []
