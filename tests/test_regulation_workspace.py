import uuid

import httpx
from fastapi.testclient import TestClient
from sion_api import models
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sqlalchemy import func, select


def fixture_report(run):
    return {
        "request_id": run,
        "input_hash": "sha256:" + "0" * 64,
        "retrieved_at": "2026-10-09T00:00:00Z",
        "as_of": "2026-10-09",
        "required_branches": ["law"],
        "results": {
            "law": {
                "status": "ok",
                "data": {},
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "branch": "law",
                        "origin_id": "law1",
                        "source_url": "https://example.com/law",
                        "publisher": "synthetic",
                        "document_id": "law1",
                        "retrieved_at": "2026-10-09T00:00:00Z",
                        "snapshot_hash": "sha256:" + "1" * 64,
                        "claim": "test",
                        "excerpt": "합성 법규 근거",
                        "location": {"article": "1"},
                    }
                ],
            }
        },
        "verification": {"verified": False, "missing": [], "conflicts": []},
        "decision": {"status": "insufficient_evidence", "reason_codes": ["REVIEWED_RULE_SET_NOT_CONFIGURED"]},
    }


def test_save_read_update_briefing_and_transactional_evidence(monkeypatch):
    monkeypatch.setenv("SION_REGULATION_GATEWAY_URL", "http://gateway")
    monkeypatch.setenv("GATEWAY_TOKEN", "test-token")
    run = str(uuid.uuid4())
    report = fixture_report(run)

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json=report)

    app = create_app(database_url="sqlite://", regulation_transport=httpx.MockTransport(handler))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        project = c.post(
            "/api/v1/entities", json={"stable_key": "p", "entity_type_id": "Project", "name": "합성 프로젝트"}
        ).json()
        assert (
            c.post("/api/v1/regulation/gateway/report", json={"question": "법규", "as_of": "2026-10-09"}).json()[
                "canonical"
            ]
            is False
        )
        body = {
            "project_id": project["id"],
            "run_id": run,
            "title": "검토",
            "notes": "회의 기록",
            "tasks": ["조례 확인"],
        }
        assert c.post("/api/v1/regulation/works", json={**body, "dry_run": True}).json()["saved"] is False
        assert c.get("/api/v1/regulation/works").json() == []
        saved = c.post("/api/v1/regulation/works", json=body)
        assert saved.status_code == 200, saved.text
        work = saved.json()["work"]
        assert work["canonical"] is False
        assert c.post("/api/v1/regulation/works", json=body).json()["existing"]
        assert len(c.get("/api/v1/regulation/works?project_id=" + project["id"]).json()) == 1
        update = {"notes": "수정 메모", "tasks": ["지구단위계획 확인"], "status": "in_review"}
        c.post("/api/v1/regulation/works/" + work["id"], json={**update, "dry_run": True})
        assert c.get("/api/v1/regulation/works/" + work["id"]).json()["notes"] == "회의 기록"
        assert c.post("/api/v1/regulation/works/" + work["id"], json=update).status_code == 200
        brief = c.get("/api/v1/regulation/works/" + work["id"] + "/briefing").text
        assert all(
            x in brief
            for x in ["합성 법규 근거", "https://example.com/law", "수정 메모", "지구단위계획 확인", "미확인"]
        )
        assert c.get("/regulation").status_code == 200
    with app.state.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(models.Evidence)) == 1
        assert s.scalar(select(func.count()).select_from(models.Relation)) == 1
        assert s.scalar(select(func.count()).select_from(models.OutboxEvent)) >= 4


def test_invalid_report_never_saved_and_scopes(monkeypatch):
    monkeypatch.setenv("SION_REGULATION_GATEWAY_URL", "http://gateway")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"bad": True}))
    policy = AuthPolicy(mode="bearer", token_scopes=(("read-token-1234567", frozenset({"read:knowledge"})),))
    app = create_app(database_url="sqlite://", regulation_transport=transport, auth_policy=policy)
    with TestClient(app) as c:
        assert c.get("/api/v1/regulation/works").status_code == 401
        c.headers["Authorization"] = "Bearer read-token-1234567"
        assert c.post("/api/v1/regulation/gateway/report", json={}).status_code == 502
        assert (
            c.post(
                "/api/v1/regulation/works",
                json={"project_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4()), "title": "x"},
            ).status_code
            == 403
        )
        assert c.get("/api/v1/regulation/works").json() == []
