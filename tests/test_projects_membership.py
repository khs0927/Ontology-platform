"""Signed-in users creating projects, inviting members and acting by role (sion_api.projects)."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_api.oidc import OidcVerifier

jwt = pytest.importorskip("jwt")
ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")

ISSUER = "https://example-ref.supabase.co/auth/v1"
ADMIN = "members-test-admin-token-0001"
KEY = ec.generate_private_key(ec.SECP256R1())


def _headers(sub, *, email=None, scopes=("write:knowledge",)):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": "authenticated", "sub": sub, "iat": now, "exp": now + 600,
        "app_metadata": {"sion_scopes": list(scopes)},
    }
    if email:
        claims["email"] = email
    return {"Authorization": "Bearer " + jwt.encode(claims, KEY, algorithm="ES256")}


OWNER = _headers("owner-1", email="owner@example.test")
VIEWER = _headers("viewer-1", email="viewer@example.test")
EDITOR = _headers("editor-1", email="editor@example.test")
STRANGER = _headers("stranger-1", email="stranger@example.test")
FREE = _headers("free-1", email="free@example.test", scopes=())
ADMIN_H = {"Authorization": f"Bearer {ADMIN}"}


@pytest.fixture()
def client(tmp_path):
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((ADMIN, frozenset({"*"})),),
        oidc=OidcVerifier(issuer=ISSUER, key_resolver=lambda _token: KEY.public_key()),
    )
    app = create_app(database_url=f"sqlite:///{tmp_path / 'm.db'}", auto_create_schema=True, auth_policy=policy)
    with TestClient(app) as test_client:
        yield test_client


def _entity(client, headers, project, key):
    return client.post(
        "/api/v1/entities",
        json={"stable_key": key, "entity_type_id": "Concept", "name": key, "properties": {"project_id": project}},
        headers=headers,
    )


def _invite(client, project, **body):
    response = client.post(f"/api/v1/projects/{project}/invites", json=body, headers=OWNER)
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_creates_a_project_and_invites_members_by_role(client):
    created = client.post("/api/v1/projects", json={"name": "  강남 신축  "}, headers=OWNER)
    assert created.status_code == 201, created.text
    project = created.json()["id"]
    assert created.json()["name"] == "강남 신축"

    listed = client.get("/api/v1/projects", headers=OWNER).json()["items"]
    assert [(p["id"], p["role"], p["can_write"]) for p in listed] == [(project, "owner", True)]
    assert client.get("/api/v1/projects", headers=STRANGER).json()["items"] == []
    assert _entity(client, OWNER, project, "by-owner").status_code == 201
    assert client.get(f"/api/v1/entities/{project}", headers=STRANGER).status_code == 404

    # Email-bound viewer invitation: only that signed-in email can use it, and only once.
    viewer_invite = _invite(client, project, role="viewer", email="Viewer@Example.test")
    assert "token_sha256" not in viewer_invite
    token = viewer_invite["token"]
    assert client.post("/api/v1/invites/accept", json={"token": token}, headers=STRANGER).status_code == 404
    accepted = client.post("/api/v1/invites/accept", json={"token": token}, headers=VIEWER)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"project_id": project, "name": "강남 신축", "role": "viewer"}
    assert client.post("/api/v1/invites/accept", json={"token": token}, headers=VIEWER).status_code == 404

    # Viewers read but never write, even with write:knowledge.
    names = {e["name"] for e in client.get("/api/v1/entities", headers=VIEWER).json()}
    assert names == {"강남 신축", "by-owner"}
    assert _entity(client, VIEWER, project, "by-viewer").status_code == 403
    owner_entity = next(e for e in client.get("/api/v1/entities", headers=VIEWER).json() if e["name"] == "by-owner")
    assert client.patch(f"/api/v1/entities/{owner_entity['id']}", json={"name": "x"}, headers=VIEWER).status_code == 403
    upload = client.post(f"/api/v1/projects/{project}/documents", params={"filename": "a.md"}, content=b"# a", headers=VIEWER)
    assert upload.status_code == 403
    assert client.get("/api/v1/projects", headers=VIEWER).json()["items"][0]["can_write"] is False

    # Open editor invitation; non-owners cannot invite or see invitations.
    editor_token = _invite(client, project, role="editor")["token"]
    assert client.post("/api/v1/invites/accept", json={"token": editor_token}, headers=EDITOR).json()["role"] == "editor"
    assert _entity(client, EDITOR, project, "by-editor").status_code == 201
    for headers in (EDITOR, VIEWER):
        assert client.post(f"/api/v1/projects/{project}/invites", json={}, headers=headers).status_code == 403
        assert client.get(f"/api/v1/projects/{project}/invites", headers=headers).status_code == 403
    assert client.post(f"/api/v1/projects/{project}/invites", json={}, headers=STRANGER).status_code == 404

    members = client.get(f"/api/v1/projects/{project}/members", headers=VIEWER).json()["items"]
    assert {(m["subject"], m["role"], m["email"]) for m in members} == {
        ("owner-1", "owner", "owner@example.test"),
        ("viewer-1", "viewer", "viewer@example.test"),
        ("editor-1", "editor", "editor@example.test"),
    }

    # Promotion applies on the next request (the membership cache is cleared).
    promoted = client.patch(f"/api/v1/projects/{project}/members/viewer-1", json={"role": "editor"}, headers=OWNER)
    assert promoted.status_code == 200
    assert _entity(client, VIEWER, project, "by-promoted").status_code == 201
    assert client.patch(f"/api/v1/projects/{project}/members/owner-1", json={"role": "viewer"}, headers=EDITOR).status_code == 403

    # Leaving removes access; the last owner can neither leave nor be demoted.
    assert client.delete(f"/api/v1/projects/{project}/members/editor-1", headers=EDITOR).status_code == 200
    assert client.get(f"/api/v1/entities/{project}", headers=EDITOR).status_code == 404
    assert client.delete(f"/api/v1/projects/{project}/members/owner-1", headers=VIEWER).status_code == 403
    assert client.delete(f"/api/v1/projects/{project}/members/owner-1", headers=OWNER).status_code == 409
    assert client.patch(f"/api/v1/projects/{project}/members/owner-1", json={"role": "editor"}, headers=OWNER).status_code == 409

    states = {i["role"]: i["state"] for i in client.get(f"/api/v1/projects/{project}/invites", headers=OWNER).json()["items"]}
    assert states == {"viewer": "accepted", "editor": "accepted"}


def test_invitations_expire_and_can_be_revoked(client):
    project = client.post("/api/v1/projects", json={"name": "p"}, headers=OWNER).json()["id"]
    revoked = _invite(client, project)
    assert client.delete(f"/api/v1/projects/{project}/invites/{revoked['id']}", headers=OWNER).json()["state"] == "revoked"
    assert client.post("/api/v1/invites/accept", json={"token": revoked["token"]}, headers=EDITOR).status_code == 404

    expired = _invite(client, project)
    from sion_api.projects import ProjectInvite

    factory = client.app.state.session_factory
    with factory() as session:
        row = session.get(ProjectInvite, __import__("uuid").UUID(expired["id"]))
        row.expires_at = row.created_at - timedelta(seconds=1)
        session.commit()
    assert client.post("/api/v1/invites/accept", json={"token": expired["token"]}, headers=EDITOR).status_code == 404
    assert client.post("/api/v1/invites/accept", json={"token": "x" * 43}, headers=EDITOR).status_code == 404


def test_free_users_join_but_cannot_create_and_creation_is_limited(client, monkeypatch):
    assert client.post("/api/v1/projects", json={"name": "p"}, headers=FREE).status_code == 403
    assert client.post("/api/v1/projects", json={"name": "p"}, headers=ADMIN_H).status_code == 403  # needs a user

    project = client.post("/api/v1/projects", json={"name": "p"}, headers=OWNER).json()["id"]
    token = _invite(client, project, role="viewer")["token"]
    assert client.post("/api/v1/invites/accept", json={"token": token}, headers=FREE).status_code == 200
    assert {e["name"] for e in client.get("/api/v1/entities", headers=FREE).json()} == {"p"}

    monkeypatch.setenv("SION_MAX_OWNED_PROJECTS", "1")
    assert client.post("/api/v1/projects", json={"name": "second"}, headers=OWNER).status_code == 409

    # Operators (unrestricted tokens) see every project and manage members.
    assert client.get(f"/api/v1/projects/{project}/members", headers=ADMIN_H).status_code == 200
    assert client.patch(f"/api/v1/projects/{project}/members/free-1", json={"role": "editor"}, headers=ADMIN_H).status_code == 200


def test_membership_migration_matches_models():
    from sion_api import migrate
    from sion_api.projects import ProjectInvite, ProjectMember

    assert "011_project_members" in migrate.CORE_SEQUENCE
    sql = (migrate.CORE_DIR / "011_project_members.sql").read_text()
    for table in (ProjectMember.__table__, ProjectInvite.__table__):
        assert f"CREATE TABLE IF NOT EXISTS {table.name}" in sql
        for column in table.columns:
            assert f"  {column.name} " in sql, column.name
