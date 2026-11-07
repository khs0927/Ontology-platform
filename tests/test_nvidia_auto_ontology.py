"""NVIDIA Auto Ontology federation: real wire contract, mocked HTTP only, no cloud key."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_api.nvidia_auto_ontology import NvidiaBridgeConfig

READ = "nvidia-integration-read-token-0001"
WRITE = "nvidia-integration-write-token-0002"
RESTRICTED = "nvidia-integration-restricted-token-0003"
API_SECRET = "nvidia-test-secret-never-disclose-0001"

POLICY = AuthPolicy(
    mode="bearer",
    token_scopes=(
        (READ, frozenset({"read:knowledge"})),
        (WRITE, frozenset({"write:knowledge"})),
        (RESTRICTED, frozenset({"read:knowledge"})),
    ),
    token_projects=((RESTRICTED, frozenset({str(uuid.UUID(int=1))})),),
)


def _client(monkeypatch, handler=None, *, ask=False):
    monkeypatch.setenv("SION_NVIDIA_AUTO_ONTOLOGY_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN", API_SECRET)
    monkeypatch.setenv("SION_NVIDIA_AUTO_ONTOLOGY_ENABLE_ASK", "1" if ask else "0")

    def unused(_request):
        raise AssertionError("unexpected NVIDIA network request")

    transport = httpx.MockTransport(handler or unused)
    app = create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        auth_policy=POLICY,
        nvidia_transport=transport,
    )
    return TestClient(app, base_url="http://localhost", client=("203.0.113.7", 47001))


def _auth(token=READ):
    return {"Authorization": f"Bearer {token}"}


def test_disabled_by_default_has_no_upstream_activity(monkeypatch):
    monkeypatch.delenv("SION_NVIDIA_AUTO_ONTOLOGY_URL", raising=False)
    monkeypatch.delenv("SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN", raising=False)
    with TestClient(
        create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=POLICY),
        client=("203.0.113.7", 47001),
    ) as client:
        response = client.get("/api/v1/nvidia/status", headers=_auth())
        assert response.status_code == 200
        assert response.json()["configured"] is False
        assert response.json()["upstream_verified"] is False
        assert client.get("/api/v1/nvidia/terms", headers=_auth()).status_code == 503


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "http://192.168.1.12:3000",
        "https://user:secret@server.example",
        "https://server.example/path",
        "https://server.example?next=evil",
        "file:///etc/passwd",
        "http://example.com#fragment",
    ],
)
def test_config_refuses_unsafe_targets(monkeypatch, url):
    monkeypatch.setenv("SION_NVIDIA_AUTO_ONTOLOGY_URL", url)
    monkeypatch.setenv("SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN", API_SECRET)
    with pytest.raises(RuntimeError):
        NvidiaBridgeConfig.from_env()


def test_config_never_exposes_secret_on_partial_setup(monkeypatch):
    monkeypatch.delenv("SION_NVIDIA_AUTO_ONTOLOGY_URL", raising=False)
    monkeypatch.setenv("SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN", API_SECRET)
    with pytest.raises(RuntimeError) as exc:
        NvidiaBridgeConfig.from_env()
    assert API_SECRET not in str(exc.value)


def test_terms_are_explicit_unverified_candidates_and_sion_is_unchanged(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        assert req.method == "GET"
        assert req.url.path == "/api/terms"
        assert req.url.params["query"] == "door"
        assert req.url.params["limit"] == "2"
        assert req.headers["x-api-key"] == API_SECRET
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "term-01",
                        "name": "Fire Door",
                        "description": "Count of fire doors",
                        "name_certified": True,
                        "description_certified": True,
                    }
                ],
                "count": 1,
                "total": 11,
            },
        )

    with _client(monkeypatch, handler) as client:
        response = client.get("/api/v1/nvidia/terms?query=door&limit=2", headers=_auth())
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["source"] == "NVIDIA/auto-ontology"
        assert data["canonical"] is False and data["read_only"] is True
        assert data["promoted"] is False and data["total"] == 11
        assert data["candidates"][0]["suggested_entity_type"] == "Concept"
        assert data["candidates"][0]["verification_state"] == "unverified"
        assert data["candidates"][0]["upstream_name_certified"] is True
        assert client.get("/api/v1/entities", headers=_auth()).json() == []
    assert len(calls) == 1


def test_ask_is_opt_in_and_has_no_upstream_call_by_default(monkeypatch):
    with _client(monkeypatch, ask=False) as client:
        response = client.post(
            "/api/v1/nvidia/ask", json={"question": "Number of doors?"}, headers=_auth()
        )
        assert response.status_code == 503
        assert "disabled" in response.text.lower()


def test_ask_uses_upstream_sse_without_executing_sql_in_sion(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url.path == "/api/chat/completions"
        assert req.method == "POST"
        assert req.headers["x-api-key"] == API_SECRET
        assert json.loads(req.content) == {"question": "How many doors?"}
        sse = "\n\n".join(
            [
                'data: {"type":"step","node":"thinking"}',
                'data: {"type":"result","answer":{"response":"2 doors","sql_code":"SELECT COUNT(*) FROM doors","sql_response_from_db":[{"count":2}]}}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(
            200,
            text=sse + "\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    with _client(monkeypatch, handler, ask=True) as client:
        response = client.post(
            "/api/v1/nvidia/ask", json={"question": "How many doors?"}, headers=_auth()
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["answer"] == "2 doors"
        assert body["sql"] == "SELECT COUNT(*) FROM doors"
        assert body["rows"] == [{"count": 2}]
        assert body["row_count"] == 1
        assert body["executed_by_sion"] is False
        assert body["canonical"] is False
        assert body["verification_state"] == "unverified"
        assert client.get("/api/v1/entities", headers=_auth()).json() == []
    assert len(calls) == 1


def test_project_scoped_token_never_federates(monkeypatch):
    def fail(_req):
        raise AssertionError("project restricted caller reached NVIDIA")
    with _client(monkeypatch, fail, ask=True) as client:
        for method, path, kwargs in [
            ("GET", "/api/v1/nvidia/status", {}),
            ("GET", "/api/v1/nvidia/terms", {}),
            ("POST", "/api/v1/nvidia/ask", {"json": {"question": "door"}}),
        ]:
            response = client.request(method, path, headers=_auth(RESTRICTED), **kwargs)
            assert response.status_code == 403


def test_sion_scope_separation_and_anonymous_requests(monkeypatch):
    with _client(monkeypatch, ask=True) as client:
        for path in ("/api/v1/nvidia/status", "/api/v1/nvidia/terms"):
            assert client.get(path).status_code == 401
            assert client.get(path, headers=_auth(WRITE)).status_code == 403
        assert client.post("/api/v1/nvidia/ask", json={"question": "ok"}).status_code == 401
        assert client.post(
            "/api/v1/nvidia/ask", json={"question": "ok"}, headers=_auth(WRITE)
        ).status_code == 403


@pytest.mark.parametrize("upstream", [302, 401, 403, 429, 500])
def test_upstream_errors_are_sanitized_and_never_follow_redirect(monkeypatch, upstream):
    def handler(req):
        return httpx.Response(
            upstream,
            json={"detail": API_SECRET},
            headers={"Location": "https://attacker.example/collect"},
        )

    with _client(monkeypatch, handler) as client:
        response = client.get("/api/v1/nvidia/terms?query=door", headers=_auth())
        assert response.status_code in {502, 503}
        assert API_SECRET not in response.text
        assert "attacker.example" not in response.text


def test_rejects_incomplete_or_false_sse_results(monkeypatch):
    def handler(req):
        return httpx.Response(
            200,
            text='data: {"type":"step","node":"think"}\n\n',
            headers={"Content-Type": "text/event-stream"},
        )

    with _client(monkeypatch, handler, ask=True) as client:
        response = client.post("/api/v1/nvidia/ask", json={"question": "door"}, headers=_auth())
        assert response.status_code == 502


def test_unknown_question_fields_do_not_escape(monkeypatch):
    with _client(monkeypatch, ask=True) as client:
        assert client.post(
            "/api/v1/nvidia/ask",
            json={"question": "door", "target_db": "other-project"},
            headers=_auth(),
        ).status_code == 422


def test_nvidia_readiness_queries_real_upstream_status_without_sql(monkeypatch):
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path))
        assert req.headers["x-api-key"] == API_SECRET
        return httpx.Response(
            200,
            json={
                "calculated": True,
                "running": False,
                "last_success_at": "2026-11-07T10:00:00Z",
                "last_failure_at": None,
            },
        )

    with _client(monkeypatch, handler) as client:
        response = client.get("/api/v1/nvidia/readiness", headers=_auth())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["upstream_reachable"] is True
        assert body["semantic_calculated"] is True
        assert body["can_execute_sql"] is None
        assert body["canonical"] is False
        assert API_SECRET not in response.text
        assert client.get("/api/v1/nvidia/readiness", headers=_auth(WRITE)).status_code == 403
        assert client.get("/api/v1/nvidia/readiness", headers=_auth(RESTRICTED)).status_code == 403
    assert seen == [("GET", "/api/semantic-compilation/status")]


@pytest.mark.parametrize("payload", [{}, {"calculated": "yes"}, ["calculated"]])
def test_nvidia_readiness_fails_closed_on_schema_changes(monkeypatch, payload):
    with _client(monkeypatch, lambda req: httpx.Response(200, json=payload)) as client:
        response = client.get("/api/v1/nvidia/readiness", headers=_auth())
        assert response.status_code == 502
        assert response.json()["detail"] == "NVIDIA readiness schema did not match the pinned API"


def test_nvidia_readiness_is_unavailable_when_integration_disabled(monkeypatch):
    monkeypatch.delenv("SION_NVIDIA_AUTO_ONTOLOGY_URL", raising=False)
    monkeypatch.delenv("SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN", raising=False)
    with TestClient(
        create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=POLICY),
        client=("203.0.113.7", 47001),
    ) as client:
        assert client.get("/api/v1/nvidia/readiness", headers=_auth()).status_code == 503
