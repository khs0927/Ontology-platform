"""Project-restricted callers on the review queue and the evidence list."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app

ADMIN = "review-test-admin-token-0001"
MEMBER = "review-test-member-token-0002"
ADMIN_H = {"Authorization": f"Bearer {ADMIN}"}
MEMBER_H = {"Authorization": f"Bearer {MEMBER}"}


@pytest.fixture()
def env(tmp_path):
    url = f"sqlite:///{tmp_path / 'r.db'}"
    seed = AuthPolicy(mode="bearer", token_scopes=((ADMIN, frozenset({"*"})),))
    ids: dict[str, str] = {}
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=seed)) as client:
        for name in ("a", "b"):
            ids[name] = client.post(
                "/api/v1/entities",
                json={"stable_key": f"proj-{name}", "entity_type_id": "Project", "name": name},
                headers=ADMIN_H,
            ).json()["id"]
            for i in (1, 2):
                ids[f"{name}{i}"] = client.post(
                    "/api/v1/entities",
                    json={"stable_key": f"e-{name}{i}", "entity_type_id": "Concept", "name": f"{name}{i}",
                          "properties": {"project_id": ids[name]}},
                    headers=ADMIN_H,
                ).json()["id"]
        for key, source, target in (("cand_a", "a1", "a2"), ("cand_b", "b1", "b2"), ("cand_x", "a1", "b1")):
            response = client.post(
                "/api/v1/relations",
                json={"stable_key": key, "source_entity_id": ids[source], "target_entity_id": ids[target],
                      "relation_type_id": "RELATED_TO", "confidence": 0.5, "source_kind": "document",
                      "properties": {"candidate": True}},
                headers=ADMIN_H,
            )
            assert response.status_code == 201, response.text
            ids[key] = response.json()["id"]
            client.post("/api/v1/evidence", json={"relation_id": ids[key], "source_uri": f"urn:{key}"}, headers=ADMIN_H)
        client.post("/api/v1/evidence", json={"entity_id": ids["b1"], "source_uri": "urn:b1"}, headers=ADMIN_H)
        client.post("/api/v1/evidence", json={"entity_id": ids["a1"], "source_uri": "urn:a1"}, headers=ADMIN_H)
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((ADMIN, frozenset({"*"})), (MEMBER, frozenset({"read:knowledge", "write:knowledge"}))),
        token_projects=((MEMBER, frozenset({ids["a"]})),),
    )
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=policy)) as client:
        yield client, ids


def test_queue_and_evidence_show_only_the_members_project(env):
    client, ids = env
    queue = client.get("/api/v1/relations/candidates", headers=MEMBER_H).json()
    assert [c["id"] for c in queue["candidates"]] == [ids["cand_a"]]
    assert queue["total"] == 1 and queue["counts"]["pending"] == 1
    assert client.get("/api/v1/relations/candidates", headers=ADMIN_H).json()["total"] == 3
    narrowed = client.get("/api/v1/relations/candidates", params={"project_id": ids["b"]}, headers=ADMIN_H).json()
    assert [c["id"] for c in narrowed["candidates"]] == [ids["cand_b"]]
    assert client.get("/api/v1/relations/candidates", params={"project_id": ids["b"]}, headers=MEMBER_H).status_code == 404

    for key in ("cand_b", "cand_x"):
        assert client.get(f"/api/v1/relations/candidates/{ids[key]}", headers=MEMBER_H).status_code == 404
        assert client.get(f"/api/v1/relations/candidates/{ids[key]}/audit", headers=MEMBER_H).status_code == 404
    assert client.get(f"/api/v1/relations/candidates/{ids['cand_a']}", headers=MEMBER_H).status_code == 200

    sources = sorted(e["source_uri"] for e in client.get("/api/v1/evidence", headers=MEMBER_H).json())
    assert sources == ["urn:a1", "urn:cand_a"]
    assert len(client.get("/api/v1/evidence", headers=ADMIN_H).json()) == 5


def test_decisions_stay_inside_the_project_and_record_the_account(env):
    client, ids = env
    for verb in ("approve", "reject"):
        for key in ("cand_b", "cand_x"):
            response = client.post(f"/api/v1/relations/candidates/{ids[key]}/{verb}", json={}, headers=MEMBER_H)
            assert response.status_code == 404, (verb, key)
    reopen = {"note": "again"}
    assert client.post(f"/api/v1/relations/candidates/{ids['cand_b']}/reopen", json=reopen, headers=MEMBER_H).status_code == 404

    bulk = {"ids": [ids["cand_a"], ids["cand_b"]], "decision": "approve", "note": "batch"}
    assert client.post("/api/v1/relations/candidates/bulk", json=bulk, headers=MEMBER_H).status_code == 404
    states = {c["id"]: c["status"] for c in client.get("/api/v1/relations/candidates?status=all", headers=ADMIN_H).json()["candidates"]}
    assert set(states.values()) == {"pending"}  # nothing was decided by the refused bulk call

    approved = client.post(
        f"/api/v1/relations/candidates/{ids['cand_a']}/approve", json={"reviewer": "someone else"}, headers=MEMBER_H
    )
    assert approved.status_code == 200, approved.text
    # Bearer tokens have no account, so the typed reviewer name is kept as before.
    assert "someone else" in approved.text
    assert client.post(
        f"/api/v1/relations/candidates/{ids['cand_a']}/reopen", json=reopen, headers=MEMBER_H
    ).status_code == 200
    bulk["ids"] = [ids["cand_a"], "not-a-uuid"]
    result = client.post("/api/v1/relations/candidates/bulk", json=bulk, headers=MEMBER_H)
    assert result.status_code == 200, result.text


def test_signed_in_reviewer_is_recorded_by_account(tmp_path):
    jwt = pytest.importorskip("jwt")
    ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")
    import time

    from sion_api.oidc import OidcVerifier

    issuer = "https://example-ref.supabase.co/auth/v1"
    private = ec.generate_private_key(ec.SECP256R1())
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((ADMIN, frozenset({"*"})),),
        oidc=OidcVerifier(issuer=issuer, key_resolver=lambda _token: private.public_key()),
    )
    url = f"sqlite:///{tmp_path / 'o.db'}"
    with TestClient(create_app(database_url=url, auto_create_schema=True, auth_policy=policy)) as client:
        project = client.post(
            "/api/v1/entities", json={"stable_key": "p", "entity_type_id": "Project", "name": "p"}, headers=ADMIN_H
        ).json()["id"]
        ends = [
            client.post(
                "/api/v1/entities",
                json={"stable_key": f"e{i}", "entity_type_id": "Concept", "name": f"e{i}", "properties": {"project_id": project}},
                headers=ADMIN_H,
            ).json()["id"]
            for i in (1, 2)
        ]
        relation = client.post(
            "/api/v1/relations",
            json={"stable_key": "c", "source_entity_id": ends[0], "target_entity_id": ends[1], "relation_type_id": "RELATED_TO",
                  "source_kind": "document", "properties": {"candidate": True}},
            headers=ADMIN_H,
        ).json()["id"]
        now = int(time.time())
        token = jwt.encode(
            {"iss": issuer, "aud": "authenticated", "sub": "user-42", "iat": now, "exp": now + 600,
             "app_metadata": {"sion_scopes": ["write:knowledge"], "sion_projects": [project]}},
            private, algorithm="ES256",
        )
        response = client.post(
            f"/api/v1/relations/candidates/{relation}/approve",
            json={"reviewer": "impersonated"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert "user:user-42" in response.text and "impersonated" not in response.text


def test_review_report_only_covers_the_members_project(env):
    client, ids = env
    # An operator approves across projects in one batch; a member approves inside project A.
    cross = {"ids": [ids["cand_b"], ids["cand_x"]], "decision": "approve", "note": "operator batch"}
    assert client.post("/api/v1/relations/candidates/bulk", json=cross, headers=ADMIN_H).status_code == 200
    own = {"ids": [ids["cand_a"]], "decision": "approve", "note": "member batch"}
    member_batch = client.post("/api/v1/relations/candidates/bulk", json=own, headers=MEMBER_H).json()["batch_id"]

    report = client.get("/api/v1/review/report", headers=MEMBER_H)
    assert report.status_code == 200, report.text
    body = report.json()
    assert [r["stable_key"] for r in body["relations"]] == ["cand_a"]
    assert sum(c["total"] for c in body["counts"].values()) == 1
    assert [b["batch_id"] for b in body["batches"]] == [member_batch]
    assert "operator batch" not in report.text

    full = client.get("/api/v1/review/report", headers=ADMIN_H).json()
    assert {r["stable_key"] for r in full["relations"]} == {"cand_a", "cand_b", "cand_x"}
    assert len(full["batches"]) == 2


def test_artifacts_are_scoped_to_the_members_projects(env):
    client, ids = env

    def artifact(key, headers, project=None):
        properties = {} if project is None else {"project_id": project}
        return client.post(
            "/api/v1/artifacts",
            json={"stable_key": key, "name": key, "storage_uri": f"urn:{key}", "properties": properties},
            headers=headers,
        )

    shared = artifact("art-shared", ADMIN_H).json()["id"]
    other = artifact("art-b", ADMIN_H, ids["b"]).json()["id"]
    assert artifact("art-none", MEMBER_H).status_code == 422
    assert artifact("art-b2", MEMBER_H, ids["b"]).status_code == 404
    mine = artifact("art-a", MEMBER_H, ids["a"].upper())
    assert mine.status_code == 201, mine.text
    assert mine.json()["properties"]["project_id"] == ids["a"]

    listed = client.get("/api/v1/artifacts", headers=MEMBER_H).json()
    assert [a["stable_key"] for a in listed] == ["art-a"]
    assert client.get(f"/api/v1/artifacts/{mine.json()['id']}", headers=MEMBER_H).status_code == 200
    for hidden in (shared, other):
        assert client.get(f"/api/v1/artifacts/{hidden}", headers=MEMBER_H).status_code == 404
    assert len(client.get("/api/v1/artifacts", headers=ADMIN_H).json()) == 3
