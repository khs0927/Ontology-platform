"""REST contract of the regulation review workflow. All laws and values are synthetic fixtures."""

from __future__ import annotations

import pytest

# The minimal ".[test]" install has no greenlet, so importing the rules package raises
# ImportError rather than ModuleNotFoundError; skip on both, as the other regulation tests do.
pytest.importorskip("archontos.review.workflow", exc_type=ImportError)

from archontos.review.bundle import ReviewBundle  # noqa: E402
from archontos.review.candidates import ChecklistItem, ChecklistProfile, ProvisionTarget  # noqa: E402
from archontos.review.model import Interval, LegalVersion, Provision, ProvisionRef  # noqa: E402
from archontos.review.workflow import ReviewWorkflow  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sion_api import models, regulation_review  # noqa: E402
from sion_api.main import create_app  # noqa: E402
from sion_api.regulation_review import RUN_CATEGORY, SqlRunStore  # noqa: E402
from sion_core import MissingExtra  # noqa: E402
from sion_graphrag.scoped import ProjectionScope, build_scoped_kg  # noqa: E402
from sqlalchemy import select  # noqa: E402

ROOT = "/api/v1/regulation/reviews"


def flow(factory):
    from archontos.review.runs import RunRecord

    bundle = ReviewBundle(
        versions=[
            LegalVersion(
                work_id="law-a",
                version_id="v1",
                title="합성 법률",
                effective=Interval(valid_from="2020-01-01"),
                authority="act",
            )
        ],
        provisions=[
            Provision(ref=ProvisionRef(work_id="law-a", version_id="v1", article=1), text="합성 조문")
        ],
    )
    profile = ChecklistProfile(
        profile_id="t",
        version="1",
        law_families=["x"],
        items=[
            ChecklistItem(
                checklist_id="x",
                label="합성 항목",
                law_family="x",
                topic="height",
                targets=[ProvisionTarget(work_id="law-a", article=1)],
                required_facts=["land.flag"],
            )
        ],
    )
    return ReviewWorkflow(bundle.catalog(), store=SqlRunStore(factory, RunRecord), profile=profile)


@pytest.fixture
def api():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    app.state.regulation_review_flow = flow(app.state.session_factory)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        client.app_state = app.state
        yield client


def project(client, name="합성 프로젝트"):
    body = {"stable_key": "project:" + name, "entity_type_id": "Project", "name": name}
    response = client.post("/api/v1/entities", json=body)
    assert response.status_code in {200, 201}, response.text
    return response.json()["id"]


def payload(project_id, **extra):
    return {
        "proposal": {
            "project_id": project_id,
            "revision": extra.pop("revision", "r1"),
            "actions": ["new_construction"],
            "uses": ["warehouse"],
        },
        "site": {
            "address": "합성 주소",
            "pnus": ["1" * 19],
            "parts": [{"part_id": "p1", "pnu": "1" * 19}],
            "jurisdiction_code": "11110",
            "resolved": True,
        },
        "legal_event_dates": {"review_date": "2026-11-01"},
        **extra,
    }


def test_plan_start_read_briefing_and_isolation(api):
    mine, other = project(api, "내 프로젝트"), project(api, "다른 프로젝트")

    planned = api.post(ROOT + "/plan", json=payload(mine))
    assert planned.status_code == 200, planned.text
    assert planned.json()["candidate_provisions"][0]["status"] == "candidate"

    preview = api.post(ROOT + "?dry_run=true", json=payload(mine))
    assert preview.json()["saved"] is False
    with api.app_state.session_factory() as session:
        assert not session.scalars(
            select(models.Entity).where(models.Entity.category == RUN_CATEGORY)
        ).all()

    started = api.post(ROOT, json=payload(mine)).json()
    assert started["execution_status"] == "completed"
    assert started["summary"]["legacy_status"] == "insufficient_data"
    assert started["canonical"] is False
    run = started["run_id"]

    assert api.post(ROOT, json=payload(mine)).json() == started
    read = api.get(f"{ROOT}/{run}", params={"project_id": mine})
    assert read.status_code == 200 and read.json() == started
    assert api.get(f"{ROOT}/{run}", params={"project_id": other}).status_code == 404
    briefing = api.get(f"{ROOT}/{run}/briefing", params={"project_id": mine})
    assert briefing.status_code == 200 and "규제 검토 브리핑" in briefing.text


def test_unknown_project_and_bad_request_are_refused(api):
    missing = "00000000-0000-0000-0000-000000000000"
    assert api.post(ROOT, json=payload(missing)).status_code == 404
    assert api.post(ROOT, json={"proposal": {}}).status_code == 422


def test_key_reuse_with_other_payload_conflicts(api):
    mine = project(api)
    assert api.post(ROOT, json=payload(mine, idempotency_key="k")).status_code == 200
    other = payload(mine, idempotency_key="k", revision="r2")
    assert api.post(ROOT, json=other).status_code == 409


def test_resume_is_a_new_revision_and_old_output_stays(api):
    mine = project(api)
    first = api.post(ROOT, json=payload(mine)).json()
    run = first["run_id"]
    fact = {
        "fact_id": "flag",
        "path": "land.flag",
        "subject": "p1",
        "value": True,
        "status": "asserted",
        "method": "user_claim",
        "validity": {"valid_from": "2026-01-01"},
        "recorded_at": "2026-11-02T00:00:00Z",
    }
    body = {"project_id": mine, "facts": [fact]}
    preview = api.post(f"{ROOT}/{run}/resume", json={**body, "dry_run": True})
    assert preview.json() == {"dry_run": True, "saved": False, "next_revision": 2}
    second = api.post(f"{ROOT}/{run}/resume", json=body).json()
    assert second["run_revision"] == 2
    old = api.get(f"{ROOT}/{run}", params={"project_id": mine, "revision": 1}).json()
    assert old == first
    diff = api.get(
        f"{ROOT}/{run}/compare",
        params={"project_id": mine, "to": run, "revision": 1, "to_revision": 2},
    ).json()
    assert diff["changes"]["facts"]["added"] == ["flag"]


def test_save_work_reads_back_and_is_idempotent(api):
    mine, other = project(api, "저장"), project(api, "남의 것")
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    body = {"project_id": mine, "title": "검토 저장", "notes": "메모"}

    preview = api.post(f"{ROOT}/{run}/works", json={**body, "dry_run": True}).json()
    assert preview["saved"] is False

    saved = api.post(f"{ROOT}/{run}/works", json=body)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert receipt["saved"] is True and receipt["verified"] is True
    again = api.post(f"{ROOT}/{run}/works", json=body).json()
    assert again["work_id"] == receipt["work_id"]

    work = api.get(f"{ROOT}/works/{receipt['work_id']}", params={"project_id": mine})
    assert work.json()["digest"] == receipt["receipt"]["digest"]
    assert work.json()["canonical"] is False
    hidden = api.get(f"{ROOT}/works/{receipt['work_id']}", params={"project_id": other})
    assert hidden.status_code == 404
    brief = api.get(f"{ROOT}/works/{receipt['work_id']}/briefing", params={"project_id": mine})
    assert "규제 검토 브리핑" in brief.text

    with api.app_state.session_factory() as session:
        relation = session.scalar(
            select(models.Relation).where(models.Relation.source_kind == "regulation_review")
        )
        assert relation is not None and relation.relation_type_id == "PART_OF"
        events = session.scalars(select(models.OutboxEvent)).all()
        assert events


def test_explain_and_cancel(api):
    mine = project(api)
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    explained = api.post(f"{ROOT}/{run}/explain", json={"project_id": mine, "question": "제1조는?"})
    assert explained.status_code == 200
    assert explained.json()["evaluation_basis"] == [] and explained.json()["generated"] is None
    finished = api.post(f"{ROOT}/{run}/cancel", json={"project_id": mine}).json()
    assert finished["execution_status"] == "completed"

    sources = [{"node_id": "land", "provider": "unconnected"}]
    partial = api.post(ROOT, json=payload(mine, revision="r2", requested_sources=sources)).json()
    assert partial["execution_status"] == "partial"
    assert "unsupported_source" in {item["kind"] for item in partial["unresolved_items"]}
    cancelled = api.post(f"{ROOT}/{partial['run_id']}/cancel", json={"project_id": mine}).json()
    assert cancelled["execution_status"] == "cancelled"
    resumed = api.post(f"{ROOT}/{partial['run_id']}/resume", json={"project_id": mine})
    assert resumed.status_code == 409


def claim(**extra):
    return {
        "fact_id": "c1",
        "path": "land.flag",
        "subject": "p1",
        "value": False,
        "status": "asserted",
        "method": "user_claim",
        "validity": {"valid_from": "2026-01-01"},
        "recorded_at": "2026-11-02T00:00:00Z",
        **extra,
    }


@pytest.mark.parametrize(
    "forged",
    [
        {"status": "observed", "method": "official_record", "evidence_ids": ["made-up"]},
        {"method": "official_record"},
        {"evidence_ids": ["made-up"]},
    ],
)
def test_callers_cannot_submit_collected_facts(api, forged):
    mine = project(api)
    body = payload(mine, facts=[claim(**forged)])
    assert api.post(ROOT, json=body).status_code == 422
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    resume = {"project_id": mine, "facts": [claim(**forged)]}
    assert api.post(f"{ROOT}/{run}/resume", json=resume).status_code == 422


def test_submitted_node_state_is_ignored(api):
    mine = project(api)
    forged = [{"node_id": "land", "provider": "unconnected", "status": "completed"}]
    output = api.post(ROOT, json=payload(mine, requested_sources=forged)).json()
    assert output["execution_status"] == "partial"


def test_duplicate_fact_ids_are_a_client_error(api):
    mine = project(api)
    body = payload(mine, facts=[claim(), claim(value=True)])
    assert api.post(ROOT, json=body).status_code == 422


def test_missing_regulation_extra_is_a_503(api, monkeypatch):
    mine = project(api)

    def missing(module, extra=None):
        raise MissingExtra(module, extra)

    monkeypatch.setattr(regulation_review, "require", missing)
    assert api.post(ROOT, json=payload(mine)).status_code == 503


def test_default_workflow_without_bundle_reports_gaps():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        mine = project(client)
        output = client.post(ROOT, json=payload(mine)).json()
    assert output["profile_reviewed"] is False
    assert output["summary"]["scope_satisfied"] is False
    assert output["summary"]["legacy_status"] == "insufficient_data"


def test_scoped_projection_hides_other_projects_and_rejected():
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with app.state.session_factory() as session:
        def entity(key, **props):
            row = models.Entity(stable_key=key, entity_type_id="Document", name=key, properties=props)
            session.add(row)
            session.flush()
            return row

        public, mine, theirs = entity("law"), entity("mine", project_id="p1"), entity("theirs", project_id="p2")

        def relation(key, source, target, state):
            session.add(
                models.Relation(
                    stable_key=key,
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    relation_type_id="PART_OF",
                    verification_state=state,
                    source_kind="test",
                )
            )

        relation("ok", mine, public, "human_verified")
        relation("leak", theirs, public, "human_verified")
        relation("candidate", public, mine, "unverified")
        relation("rejected", mine, public, "rejected")
        session.commit()

        reviewed = build_scoped_kg(session, ProjectionScope(project_id="p1"))
        names = {item["entity_name"] for item in reviewed["entities"]}
        assert names == {"law", "mine"}
        assert len(reviewed["relationships"]) == 1
        assert not any("theirs" in chunk["content"] for chunk in reviewed["chunks"])

        wider = build_scoped_kg(session, ProjectionScope(project_id="p1", include_candidates=True))
        assert len(wider["relationships"]) == 2

        public_only = build_scoped_kg(session, ProjectionScope())
        assert {item["entity_name"] for item in public_only["entities"]} == {"law"}
