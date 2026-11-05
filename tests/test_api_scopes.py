"""Route-coverage and scope-separation tests for the Sion API (issue #71 step C).

Every FastAPI route must be either an explicitly allowlisted public route or guarded by a
``require_scope`` dependency. Every mutating route (POST/PUT/PATCH/DELETE) must require a
``write:*`` scope unless it is allowlisted below as a read-only computation. Adding a new
route without a scope, or a new mutating route with only a read scope, fails these tests.
"""

from __future__ import annotations

import logging
import re
import uuid

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from test_regulation_workspace import fixture_report

READ = "scope-test-read-token-0001"
WRITE = "scope-test-write-token-0002"
ADMIN = "scope-test-admin-token-0003"
PROJECT_A = str(uuid.UUID(int=0xA))

RESTRICTED = "scope-test-project-a-token-0004"

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Unauthenticated by design. Keep this list short and justified.
PUBLIC_ROUTES = {
    ("GET", "/health"),  # liveness probe; returns no knowledge data
    ("GET", "/health/live"),  # liveness probe; no auth, no database access
    ("GET", "/health/ready"),  # readiness probe; read-only SELECT 1, no connection details
    ("GET", "/review"),  # static HTML shell; data calls behind it are scoped
    ("GET", "/map"),  # static HTML shell; data calls behind it are scoped
    ("GET", "/openapi.json"),  # FastAPI schema
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}

# POST routes that compute an answer without persisting anything. They need a read scope.
READ_ONLY_POSTS = {
    "/api/v1/vector/search",  # similarity search over stored embeddings
    "/api/v1/analyze/dxf",  # GOD-CAD analysis of a confined server file; no writes
    "/api/v1/graphrag/query",  # LightRAG query; derived answer, canonical=False
    "/api/v1/regulation/evaluate",  # ArchOntos rule evaluation over request facts
    "/api/v1/regulation/gateway/report",  # advisory gateway report; not saved
}

# Routes that apply the project ACL themselves and therefore accept project-restricted tokens.
PROJECT_SCOPED_ROUTES = {
    ("GET", "/regulation"),
    ("GET", "/api/v1/regulation/summary"),  # applies the project ACL itself (project_summary.project_scope)
    ("GET", "/api/v1/regulation/works"),
    ("POST", "/api/v1/regulation/works"),
    ("GET", "/api/v1/regulation/works/{work_id}"),
    ("POST", "/api/v1/regulation/works/{work_id}"),
    ("GET", "/api/v1/regulation/works/{work_id}/briefing"),
}


def _policy(restricted_projects: frozenset[str] = frozenset({PROJECT_A})) -> AuthPolicy:
    return AuthPolicy(
        mode="bearer",
        token_scopes=(
            (READ, frozenset({"read:knowledge", "read:aec"})),
            (WRITE, frozenset({"write:knowledge"})),
            (ADMIN, frozenset({"*"})),
            (RESTRICTED, frozenset({"read:knowledge", "write:knowledge"})),
        ),
        token_projects=((RESTRICTED, restricted_projects),),
    )


def _app(database_url: str = "sqlite://", policy: AuthPolicy | None = None, **kwargs):
    return create_app(database_url=database_url, auto_create_schema=True, auth_policy=policy or _policy(), **kwargs)


def _scope_deps(dependant) -> list:
    found = []
    for sub in dependant.dependencies:
        if hasattr(sub.call, "required_scope"):
            found.append(sub.call)
        found.extend(_scope_deps(sub))
    return found


def _routes(app):
    """(method, path, [scope dependencies]) for every method of every route."""
    rows = []
    for route in app.routes:
        methods = sorted((getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"})
        deps = _scope_deps(route.dependant) if isinstance(route, APIRoute) else []
        rows.extend((method, route.path, deps) for method in methods)
    return rows


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


@pytest.fixture(scope="module")
def app():
    return _app()


def test_every_route_is_public_or_scoped(app):
    unprotected = [(m, p) for m, p, deps in _routes(app) if not deps and (m, p) not in PUBLIC_ROUTES]
    assert unprotected == [], f"routes without require_scope (add a scope or justify in PUBLIC_ROUTES): {unprotected}"
    scoped_public = [(m, p) for m, p, deps in _routes(app) if deps and (m, p) in PUBLIC_ROUTES]
    assert scoped_public == []


def test_every_mutating_route_requires_a_write_scope(app):
    offenders = []
    for method, path, deps in _routes(app):
        if method not in MUTATING or (method, path) in PUBLIC_ROUTES:
            continue
        scopes = {dep.required_scope for dep in deps}
        if path in READ_ONLY_POSTS and method == "POST":
            assert scopes and all(scope.startswith("read:") for scope in scopes), (method, path, scopes)
            continue
        if not any(scope.startswith("write:") for scope in scopes):
            offenders.append((method, path, sorted(scopes)))
    assert offenders == [], f"mutating routes without a write scope: {offenders}"


def test_every_read_route_requires_a_read_scope(app):
    offenders = [
        (m, p, sorted(d.required_scope for d in deps))
        for m, p, deps in _routes(app)
        if m == "GET" and deps and not any(d.required_scope.startswith("read:") for d in deps)
    ]
    assert offenders == []


def test_allowlists_are_not_stale(app):
    present = {(m, p) for m, p, _ in _routes(app)}
    assert {(m, p) for m, p in PUBLIC_ROUTES if p != "/docs/oauth2-redirect"} <= present
    assert {("POST", p) for p in READ_ONLY_POSTS} <= present
    assert PROJECT_SCOPED_ROUTES <= present


def test_project_scoped_routes_are_explicit(app):
    marked = {(m, p) for m, p, deps in _routes(app) if any(getattr(d, "project_scoped", False) for d in deps)}
    assert marked == PROJECT_SCOPED_ROUTES


def test_read_token_is_rejected_on_every_mutating_route(app):
    with TestClient(app) as client:
        for method, path, deps in _routes(app):
            if method not in MUTATING or not deps or path in READ_ONLY_POSTS:
                continue
            response = client.request(method, _concrete(path), json={}, headers={"Authorization": f"Bearer {READ}"})
            assert response.status_code == 403, (method, path, response.status_code)
            assert "write:" in response.json()["detail"]


def test_write_token_is_rejected_on_every_read_route(app):
    with TestClient(app) as client:
        for method, path, deps in _routes(app):
            scopes = {d.required_scope for d in deps}
            if not scopes or any(scope.startswith("write:") for scope in scopes):
                continue
            response = client.request(method, _concrete(path), json={}, headers={"Authorization": f"Bearer {WRITE}"})
            assert response.status_code == 403, (method, path, response.status_code)


def test_anonymous_remote_caller_is_rejected_everywhere(app):
    with TestClient(app) as client:
        for method, path, deps in _routes(app):
            if deps:
                assert client.request(method, _concrete(path), json={}).status_code == 401, (method, path)


def test_write_scope_does_not_imply_read_but_admin_has_both(app):
    with TestClient(app) as client:
        assert client.get("/api/v1/entities", headers={"Authorization": f"Bearer {WRITE}"}).status_code == 403
        assert client.get("/api/v1/entities", headers={"Authorization": f"Bearer {ADMIN}"}).status_code == 200
        created = client.post(
            "/api/v1/entities",
            json={"stable_key": "scope-e", "entity_type_id": "Project", "name": "synthetic"},
            headers={"Authorization": f"Bearer {WRITE}"},
        )
        assert created.status_code == 201, created.text


def test_local_dev_modes_stay_token_free():
    for mode in ("local-only", "local-or-bearer"):
        policy = AuthPolicy(mode=mode, token_scopes=((ADMIN, frozenset({"*"})),) if mode != "local-only" else ())
        app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy)
        with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
            assert client.get("/api/v1/entities").status_code == 200
            assert (
                client.post(
                    "/api/v1/entities", json={"stable_key": "local", "entity_type_id": "Project", "name": "local"}
                ).status_code
                == 201
            )


# --- tokens are never echoed or logged -------------------------------------------------


def test_tokens_are_never_echoed_or_logged(app, caplog):
    unknown = "scope-test-unknown-token-9999"
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        responses = [
            client.get("/api/v1/entities", headers={"Authorization": f"Bearer {unknown}"}),
            client.post("/api/v1/entities", json={}, headers={"Authorization": f"Bearer {READ}"}),
            client.get("/api/v1/entities", headers={"Authorization": f"Bearer {WRITE}"}),
            client.get("/api/v1/entities", headers={"Authorization": f"Bearer {RESTRICTED}"}),
        ]
    assert [r.status_code for r in responses] == [401, 403, 403, 403]
    for response in responses:
        blob = response.text + repr(dict(response.headers))
        for token in (unknown, READ, WRITE, RESTRICTED):
            assert token not in blob
    for token in (unknown, READ, WRITE, RESTRICTED):
        assert token not in caplog.text


def test_principal_never_carries_the_token():
    policy = _policy()
    principal = policy._principal_for_authorization(f"Bearer {RESTRICTED}")
    assert principal is not None and principal.projects == frozenset({PROJECT_A})
    assert RESTRICTED not in repr(principal)


# --- configuration --------------------------------------------------------------------


def test_from_env_accepts_legacy_and_project_grants(monkeypatch):
    monkeypatch.setenv("SION_API_AUTH_MODE", "bearer")
    monkeypatch.setenv(
        "SION_API_TOKENS_JSON",
        '{"%s": ["read:knowledge"], "%s": {"scopes": ["read:knowledge", "write:knowledge"], "projects": ["%s"]}}'
        % (READ, RESTRICTED, PROJECT_A.upper()),
    )
    policy = AuthPolicy.from_env()
    assert dict(policy.token_scopes)[READ] == frozenset({"read:knowledge"})
    assert dict(policy.token_projects) == {RESTRICTED: frozenset({PROJECT_A})}


@pytest.mark.parametrize(
    "grant",
    [
        '{"scopes": ["read:knowledge"], "projects": []}',
        '{"scopes": ["read:knowledge"], "projects": ["not-a-uuid"]}',
        '{"scopes": ["read:knowledge"], "projects": [1]}',
        '{"scopes": [], "projects": ["%s"]}' % PROJECT_A,
        '{"scopes": ["read:knowledge"], "tenant": "x"}',
    ],
)
def test_from_env_rejects_bad_project_grants(monkeypatch, grant):
    monkeypatch.setenv("SION_API_AUTH_MODE", "bearer")
    monkeypatch.setenv("SION_API_TOKENS_JSON", '{"%s": %s}' % (RESTRICTED, grant))
    with pytest.raises(RuntimeError) as excinfo:
        AuthPolicy.from_env()
    assert RESTRICTED not in str(excinfo.value)


def test_invalid_tokens_json_error_does_not_echo_secret(monkeypatch):
    monkeypatch.setenv("SION_API_AUTH_MODE", "bearer")
    monkeypatch.setenv("SION_API_TOKENS_JSON", '{"%s": [' % RESTRICTED)
    with pytest.raises(RuntimeError) as excinfo:
        AuthPolicy.from_env()
    assert RESTRICTED not in str(excinfo.value)
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__


# --- project ACL ----------------------------------------------------------------------


def test_project_acl_on_regulation_works(monkeypatch, tmp_path):
    monkeypatch.setenv("SION_REGULATION_GATEWAY_URL", "http://gateway")
    gateway_calls = []

    def handler(request):
        run = request.url.path.rsplit("/", 1)[-1]
        gateway_calls.append(run)
        return httpx.Response(200, json=fixture_report(run))

    transport = httpx.MockTransport(handler)
    database_url = f"sqlite:///{tmp_path / 'acl.db'}"
    admin = {"Authorization": f"Bearer {ADMIN}"}
    limited = {"Authorization": f"Bearer {RESTRICTED}"}

    # Seed two projects with one saved work each (project ids are server-assigned).
    works = {}
    with TestClient(_app(database_url, regulation_transport=transport)) as client:
        for name in ("a", "b"):
            project = client.post(
                "/api/v1/entities",
                json={"stable_key": f"acl-{name}", "entity_type_id": "Project", "name": name},
                headers=admin,
            )
            assert project.status_code == 201, project.text
            project_id = project.json()["id"]
            saved = client.post(
                "/api/v1/regulation/works",
                json={"project_id": project_id, "run_id": str(uuid.uuid4()), "title": name},
                headers=admin,
            )
            assert saved.status_code == 200, saved.text
            works[name] = (project_id, saved.json()["work"]["id"])
    (a_project, a_work), (b_project, b_work) = works["a"], works["b"]

    app = _app(database_url, policy=_policy(frozenset({a_project})), regulation_transport=transport)
    with TestClient(app) as client:
        # Admin (unrestricted) sees both; the restricted token sees only project A.
        assert len(client.get("/api/v1/regulation/works", headers=admin).json()) == 2
        listed = client.get("/api/v1/regulation/works", headers=limited).json()
        assert [w["id"] for w in listed] == [a_work]
        assert client.get(f"/api/v1/regulation/works?project_id={a_project}", headers=limited).status_code == 200
        assert client.get(f"/api/v1/regulation/works?project_id={b_project}", headers=limited).status_code == 404

        assert client.get(f"/api/v1/regulation/works/{a_work}", headers=limited).status_code == 200
        assert client.get(f"/api/v1/regulation/works/{b_work}", headers=limited).status_code == 404
        assert client.get(f"/api/v1/regulation/works/{b_work}/briefing", headers=limited).status_code == 404
        update = {"notes": "n", "tasks": [], "status": "in_review"}
        assert client.post(f"/api/v1/regulation/works/{b_work}", json=update, headers=limited).status_code == 404
        assert client.post(f"/api/v1/regulation/works/{a_work}", json=update, headers=limited).status_code == 200

        # ACL is checked before any data access or gateway call for a foreign project.
        calls_before = len(gateway_calls)
        denied = client.post(
            "/api/v1/regulation/works",
            json={"project_id": b_project, "run_id": str(uuid.uuid4()), "title": "x"},
            headers=limited,
        )
        assert denied.status_code == 404
        assert len(gateway_calls) == calls_before

        # Cross-project routes fail closed for project-restricted tokens.
        for path in ("/api/v1/entities", "/api/v1/graph", "/api/v1/evidence", "/api/v1/relations/candidates"):
            assert client.get(path, headers=limited).status_code == 403, path
        assert client.post("/api/v1/regulation/gateway/report", json={}, headers=limited).status_code == 403
