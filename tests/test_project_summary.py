from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sion_api import models
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_api.project_summary import MAX_PAGE_SIZE, RateLimiter, SummaryLimits

URL = "/api/v1/regulation/summary"
READ = "summary-read-token-0001"
WRITE_ONLY = "summary-write-token-0001"
ADMIN = "summary-admin-token-0001"


def seed(app, count=3, works_per_project=2):
    """Synthetic projects plus saved works carrying a deliberately large report payload."""
    with app.state.session_factory() as s:
        projects = []
        for i in range(count):
            project = models.Entity(
                stable_key=f"summary-project-{i}", entity_type_id="Project", name=f"합성 프로젝트 {i}"
            )
            s.add(project)
            s.flush()
            projects.append(str(project.id))
            for j in range(works_per_project):
                s.add(
                    models.Entity(
                        stable_key=f"regulation-work:{project.id}:{j}",
                        entity_type_id="Document",
                        name=f"검토 {i}-{j}",
                        category="regulation_work",
                        properties={
                            "project_id": str(project.id),
                            "run_id": str(uuid.uuid4()),
                            "canonical": False,
                            "status": "done" if j == 0 else "open",
                            "notes": "",
                            "tasks": [],
                            "report": {
                                "as_of": "2026-10-09",
                                "decision": {"status": "insufficient_evidence", "reason_codes": []},
                                "results": {"law": {"evidence": [{"excerpt": "x" * 20_000}]}},
                            },
                        },
                    )
                )
        s.add(models.Entity(stable_key="summary-not-project", entity_type_id="Document", name="문서"))
        s.commit()
    return sorted(projects)


def local_client(app):
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))


@pytest.fixture
def local_app(monkeypatch):
    monkeypatch.delenv("SION_SUMMARY_RATE_LIMIT", raising=False)
    monkeypatch.delenv("SION_SUMMARY_MAX_BYTES", raising=False)
    return create_app(database_url="sqlite://", auth_policy=AuthPolicy(mode="local-only"))


def bearer_app(projects_for_read=()):
    read_scopes = frozenset({"read:knowledge", *(f"project:{pid}" for pid in projects_for_read)})
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=(
            (READ, read_scopes),
            (WRITE_ONLY, frozenset({"write:knowledge"})),
            (ADMIN, frozenset({"*"})),
        ),
    )
    return create_app(database_url="sqlite://", auth_policy=policy)


def test_summary_is_small_and_never_returns_report_payload(local_app):
    projects = seed(local_app)
    with local_client(local_app) as c:
        response = c.get(URL)
        assert response.status_code == 200, response.text
        body = response.json()
    assert body["read_only"] is True and body["canonical"] is False
    assert [item["project_id"] for item in body["items"]] == projects
    first = body["items"][0]
    assert first["work_count"] == 2
    assert first["status_counts"] == {"open": 1, "in_review": 0, "done": 1}
    assert first["latest_work"]["decision_status"] == "insufficient_evidence"
    assert first["latest_work"]["as_of"] == "2026-10-09"
    assert "report" not in json.dumps(body)
    assert len(response.content) < 4096


def test_project_filter(local_app):
    projects = seed(local_app)
    with local_client(local_app) as c:
        body = c.get(URL, params={"project_id": [projects[2], projects[0]]}).json()
        assert [item["project_id"] for item in body["items"]] == [projects[0], projects[2]]
        assert c.get(URL, params={"project_id": str(uuid.uuid4())}).json()["items"] == []
        assert c.get(URL, params={"project_id": "not-a-uuid"}).status_code == 422


def test_cursor_pagination_and_max_page_size(local_app):
    projects = seed(local_app, count=5, works_per_project=0)
    with local_client(local_app) as c:
        seen, cursor = [], None
        while True:
            params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
            body = c.get(URL, params=params).json()
            assert len(body["items"]) <= 2
            seen.extend(item["project_id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert seen == projects
        assert c.get(URL, params={"limit": MAX_PAGE_SIZE + 1}).status_code == 422
        assert c.get(URL, params={"limit": 0}).status_code == 422


def test_response_size_bound_truncates_and_resumes(local_app):
    with local_app.state.session_factory() as s:
        for i in range(30):
            s.add(models.Entity(stable_key=f"long-{i:02d}", entity_type_id="Project", name="긴이름" * 300))
        s.commit()
    local_app.state.summary_limits = SummaryLimits(max_bytes=4096)
    with local_client(local_app) as c:
        seen, cursor, pages = [], None, 0
        while True:
            response = c.get(URL, params={"limit": MAX_PAGE_SIZE, **({"cursor": cursor} if cursor else {})})
            assert len(response.content) <= 4096
            body = response.json()
            pages += 1
            seen.extend(item["project_id"] for item in body["items"])
            assert all(len(item["project_name"]) <= 200 for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                assert body["truncated"] is False
                break
            assert body["truncated"] is True
        assert len(seen) == len(set(seen)) == 30
        assert pages > 1


def test_rate_limit_per_client(local_app):
    seed(local_app, count=1)
    clock = [0.0]
    local_app.state.summary_rate_limiter = RateLimiter(2, 60, clock=lambda: clock[0])
    with local_client(local_app) as c:
        assert c.get(URL).status_code == 200
        assert c.get(URL).status_code == 200
        limited = c.get(URL)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1
        clock[0] = 61.0
        assert c.get(URL).status_code == 200


def test_rate_limit_is_keyed_per_token():
    app = bearer_app()
    app.state.summary_rate_limiter = RateLimiter(1, 60, clock=lambda: 0.0)
    with TestClient(app) as c:
        assert c.get(URL, headers={"Authorization": f"Bearer {READ}"}).status_code == 200
        assert c.get(URL, headers={"Authorization": f"Bearer {READ}"}).status_code == 429
        assert c.get(URL, headers={"Authorization": f"Bearer {ADMIN}"}).status_code == 200


def test_rate_limiter_from_env(monkeypatch):
    monkeypatch.setenv("SION_SUMMARY_RATE_LIMIT", "5/10")
    limiter = RateLimiter.from_env()
    assert (limiter.max_requests, limiter.window_seconds) == (5, 10.0)
    monkeypatch.setenv("SION_SUMMARY_RATE_LIMIT", "0")
    assert RateLimiter.from_env().enabled is False
    monkeypatch.setenv("SION_SUMMARY_RATE_LIMIT", "lots")
    with pytest.raises(RuntimeError):
        RateLimiter.from_env()


def test_auth_rejection_requires_read_scope():
    app = bearer_app()
    with TestClient(app) as c:
        assert c.get(URL).status_code == 401
        assert c.get(URL, headers={"Authorization": "Bearer wrong-token-000000"}).status_code == 401
        assert c.get(URL, headers={"Authorization": f"Bearer {WRITE_ONLY}"}).status_code == 403
        assert c.get(URL, headers={"Authorization": f"Bearer {READ}"}).status_code == 200


def test_remote_access_rejected_in_local_only_mode(local_app):
    with TestClient(local_app) as c:  # default testclient peer is not loopback
        assert c.get(URL).status_code == 403


def test_project_scoped_token_is_rejected_before_reading_data():
    allowed_id = str(uuid.uuid4())
    app = bearer_app(projects_for_read=[allowed_id])
    seed(app, count=2)
    with app.state.session_factory() as s:
        s.add(models.Entity(id=uuid.UUID(allowed_id), stable_key="acl-project", entity_type_id="Project", name="허용"))
        s.commit()
    with app.state.session_factory() as s:
        others = [
            str(row.id)
            for row in s.query(models.Entity).filter_by(entity_type_id="Project")
            if str(row.id) != allowed_id
        ]

    def fail_session():
        raise AssertionError("database must not be read for a disallowed project")

    with TestClient(app) as c:
        read = {"Authorization": f"Bearer {READ}"}
        body = c.get(URL, headers=read).json()
        assert [item["project_id"] for item in body["items"]] == [allowed_id]
        assert c.get(URL, headers=read, params={"project_id": allowed_id}).status_code == 200
        admin = c.get(URL, headers={"Authorization": f"Bearer {ADMIN}"}).json()
        assert len(admin["items"]) == 3

        # Swap the session dependency so any data access would fail loudly.
        route = next(r for r in app.routes if getattr(r, "path", None) == URL)
        session_dep = next(d.call for d in route.dependant.dependencies if d.name == "session")
        app.dependency_overrides[session_dep] = fail_session
        denied = c.get(URL, headers=read, params={"project_id": [allowed_id, others[0]]})
        assert denied.status_code == 403


def test_malformed_project_scope_fails_closed():
    app = bearer_app(projects_for_read=["not-a-uuid"])
    seed(app, count=2)
    with TestClient(app) as c:
        body = c.get(URL, headers={"Authorization": f"Bearer {READ}"}).json()
        assert body["items"] == [] and body["next_cursor"] is None
