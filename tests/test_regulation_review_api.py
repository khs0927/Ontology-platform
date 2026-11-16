"""REST contract of the regulation review workflow. All laws and values are synthetic fixtures."""

from __future__ import annotations

import pytest

# The minimal ".[test]" install has no greenlet, so importing the rules package raises
# ImportError rather than ModuleNotFoundError; skip on both, as the other regulation tests do.
pytest.importorskip("sion_regulation.review.workflow", exc_type=ImportError)

from fastapi.testclient import TestClient  # noqa: E402
from sion_api import models, regulation_review  # noqa: E402
from sion_api.main import create_app  # noqa: E402
from sion_api.regulation_review import RUN_CATEGORY, SqlRunStore  # noqa: E402
from sion_core import MissingExtra  # noqa: E402
from sion_graphrag.scoped import ProjectionScope, build_scoped_kg  # noqa: E402
from sion_regulation.review.bundle import ReviewBundle  # noqa: E402
from sion_regulation.review.candidates import ChecklistItem, ChecklistProfile, ProvisionTarget  # noqa: E402
from sion_regulation.review.model import Interval, LegalVersion, Provision, ProvisionRef  # noqa: E402
from sion_regulation.review.workflow import ReviewWorkflow  # noqa: E402
from sqlalchemy import select  # noqa: E402

ROOT = "/api/v1/regulation/reviews"


def flow(factory):
    from sion_regulation.review.runs import RunRecord

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


@pytest.mark.parametrize(
    "path",
    [
        "document.district_plan_decision",
        "designation.query_complete",
        "designation.district_unit_plan",
        "legal.is_farmland",
        "land.jimok",
    ],
)
def test_claims_on_collection_only_paths_are_refused(api, path):
    """Documents, designations, legal status and query completeness come only from collection."""

    mine = project(api)
    body = payload(mine, facts=[claim(path=path, value=True)])
    refused = api.post(ROOT, json=body)
    assert refused.status_code == 422
    assert "resolved only by collection" in str(refused.json())
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    resume = {"project_id": mine, "facts": [claim(path=path, value=True)]}
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


def test_rejected_resume_leaves_no_output_less_revision(api):
    mine = project(api)
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    first = {"project_id": mine, "facts": [claim(value=True)]}
    assert api.post(f"{ROOT}/{run}/resume", json=first).status_code == 200
    second = api.get(f"{ROOT}/{run}", params={"project_id": mine}).json()
    corrected = {"project_id": mine, "facts": [claim(value=False)]}
    assert api.post(f"{ROOT}/{run}/resume", json=corrected).status_code == 409
    # The rejected supplement opened no revision and rewrote none.
    assert api.get(f"{ROOT}/{run}", params={"project_id": mine}).json() == second
    record = api.app_state.regulation_review_flow.store.load(run, 1)
    assert "supplement" not in record.context
    third = api.post(f"{ROOT}/{run}/resume", json={"project_id": mine})
    assert third.status_code == 200 and third.json()["run_revision"] == 3
    work = api.post(f"{ROOT}/{run}/works", json={"project_id": mine, "title": "t"})
    assert work.status_code == 200


def test_in_flight_run_is_neither_restarted_nor_resumed(api):
    from datetime import UTC, datetime, timedelta

    mine = project(api)
    body = payload(mine, idempotency_key="k-in-flight")
    run = api.post(ROOT, json=body).json()["run_id"]
    store = api.app_state.regulation_review_flow.store
    record = store.load(run)
    # Another worker holds a live lease on a new revision that is still running.
    record.run_revision += 1
    record.output = None
    record.status = record.status.RUNNING
    record.lease_owner = "other-worker"
    record.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
    store.save(record)
    retried = api.post(ROOT, json=body)
    assert retried.status_code == 200
    assert retried.json()["execution_status"] == "running"
    assert store.load(run).lease_owner == "other-worker"
    resumed = api.post(f"{ROOT}/{run}/resume", json={"project_id": mine})
    assert resumed.status_code == 409
    assert store.revisions(run) == [1, 2]


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


def test_scoped_projection_hides_other_project_entities_and_part_of_material():
    """S25: a Project entity and anything reaching it only by PART_OF is that project's material."""

    app = create_app(database_url="sqlite://", auto_create_schema=True)
    with app.state.session_factory() as session:

        def entity(key, kind="Document", **props):
            row = models.Entity(stable_key=key, entity_type_id=kind, name=key, properties=props)
            session.add(row)
            session.flush()
            return row

        law = entity("law")
        mine = entity("project:mine", kind="Project")
        theirs = models.Entity(
            stable_key="project:secret-client",
            entity_type_id="Project",
            name="비공개 고객 물류센터",
            properties={"address": "서울 비공개 주소"},
        )
        session.add(theirs)
        session.flush()
        my_note = entity("my-note")
        folder = entity("secret-folder")
        secret_doc = entity("secret-doc")

        def part_of(key, source, target, state="human_verified"):
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

        part_of("my-note:project", my_note, mine)
        part_of("folder:project", folder, theirs, state="rejected")
        part_of("secret-doc:folder", secret_doc, folder)
        part_of("secret-doc:law", secret_doc, law)
        session.commit()

        # The scope id may arrive in another UUID spelling; it still names the same project.
        scoped = build_scoped_kg(session, ProjectionScope(project_id=str(mine.id).upper()))
        names = {item["entity_name"] for item in scoped["entities"]}
        assert names == {"law", "project:mine", "my-note"}
        text = "\n".join(chunk["content"] for chunk in scoped["chunks"])
        assert "비공개" not in text and "secret" not in text

        public_only = build_scoped_kg(session, ProjectionScope())
        assert {item["entity_name"] for item in public_only["entities"]} == {"law"}
        assert public_only["relationships"] == []


def work_rows(api):
    from sion_api.regulation_review import WORK_CATEGORY

    with api.app_state.session_factory() as session:
        query = select(models.Entity).where(models.Entity.category == WORK_CATEGORY)
        return session.scalars(query).all()


def test_dry_run_save_has_no_side_effects(api):
    mine = project(api)
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    body = {"project_id": mine, "title": "t", "notes": "draft"}
    preview = api.post(f"{ROOT}/{run}/works", json={**body, "dry_run": True})
    assert preview.status_code == 200 and preview.json()["saved"] is False
    assert api.app_state.regulation_review_flow.outbox.pending() == []
    assert work_rows(api) == []
    # The user edits the notes after the preview; the real save goes through.
    saved = api.post(f"{ROOT}/{run}/works", json={**body, "notes": "final"})
    assert saved.status_code == 200, saved.text


def test_resave_with_other_notes_conflicts_on_the_stored_row(api):
    mine = project(api)
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    body = {"project_id": mine, "title": "t", "notes": "A"}
    first = api.post(f"{ROOT}/{run}/works", json=body)
    assert first.status_code == 200
    other = {**body, "notes": "B"}
    refused = api.post(f"{ROOT}/{run}/works", json=other)
    assert refused.status_code == 409
    assert refused.json() == {"detail": "this run revision was already saved with other content"}
    # A restarted process has an empty outbox; the stored row still decides.
    api.app_state.regulation_review_flow = flow(api.app_state.session_factory)
    assert api.post(f"{ROOT}/{run}/works", json=other).status_code == 409
    again = api.post(f"{ROOT}/{run}/works", json=body)
    assert again.status_code == 200 and again.json()["work_id"] == first.json()["work_id"]
    work = api.get(f"{ROOT}/works/{first.json()['work_id']}", params={"project_id": mine})
    assert work.json()["notes"] == "A"


def test_cancelled_run_is_refused_and_writes_no_row(api):
    mine = project(api)
    body = payload(mine, requested_sources=[{"node_id": "n", "provider": "no-executor"}])
    run = api.post(ROOT, json=body).json()
    assert run["execution_status"] == "partial"
    cancel = api.post(f"{ROOT}/{run['run_id']}/cancel", json={"project_id": mine})
    assert cancel.json()["execution_status"] == "cancelled"
    for _ in range(2):
        save = api.post(f"{ROOT}/{run['run_id']}/works", json={"project_id": mine, "title": "t"})
        assert save.status_code == 409
    assert work_rows(api) == []


def test_saved_output_digest_matches_the_receipt(api):
    from sion_regulation.review.model import canonical_digest

    mine = project(api)
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    saved = api.post(f"{ROOT}/{run}/works", json={"project_id": mine, "title": "t"}).json()
    work = api.get(f"{ROOT}/works/{saved['work_id']}", params={"project_id": mine}).json()
    assert canonical_digest(work["output"]) == saved["receipt"]["digest"] == work["digest"]


def test_idempotency_keys_are_scoped_per_project(api):
    mine, other = project(api, "A"), project(api, "B")
    first = api.post(ROOT, json=payload(mine, idempotency_key="k1"))
    assert first.status_code == 200
    second = api.post(ROOT, json=payload(other, idempotency_key="k1"))
    assert second.status_code == 200, second.text
    assert second.json()["run_id"] != first.json()["run_id"]
    assert api.post(ROOT, json=payload(mine, idempotency_key="k1")).json() == first.json()


def test_project_id_spelling_is_normalised(api):
    mine = project(api)
    variant = mine.replace("-", "").upper()
    started = api.post(ROOT, json=payload(variant))
    assert started.status_code == 200, started.text
    assert started.json()["project_id"] == mine
    run = started.json()["run_id"]
    assert api.get(f"{ROOT}/{run}", params={"project_id": mine}).status_code == 200
    assert api.get(f"{ROOT}/{run}", params={"project_id": variant}).status_code == 200
    save = api.post(f"{ROOT}/{run}/works", json={"project_id": mine, "title": "t"})
    assert save.status_code == 200, save.text
    assert api.post(ROOT, json=payload(mine)).json()["run_id"] == run
    assert api.post(ROOT + "/plan", json=payload(variant)).status_code == 200


def test_resume_while_in_flight_is_a_fixed_409(api):
    from datetime import UTC, datetime, timedelta

    mine = project(api)
    run = api.post(ROOT, json=payload(mine)).json()["run_id"]
    store = api.app_state.regulation_review_flow.store
    record = store.load(run)
    record.run_revision += 1
    record.output = None
    record.status = record.status.RUNNING
    record.lease_owner = "other-worker"
    record.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
    store.save(record)
    resumed = api.post(f"{ROOT}/{run}/resume", json={"project_id": mine})
    assert resumed.status_code == 409
    assert resumed.json() == {"detail": "run is still in flight; retry later"}
