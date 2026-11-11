"""REST surface of the overlapping-regulation review workflow (sion_regulation.review).

Rule compilation and evaluation go through the pinned ArchOntos engine (``archontos.rules``).
This module only stores run records and saved works in the canonical project workspace. A run
record is a Document entity, so the existing outbox and Drive export carry it. Writes keep the
platform's own scopes and ``dry_run``; there is no Jev step on this path. Results stay advisory:
``canonical`` is false and nothing here becomes an ontology fact.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sion_core import MissingExtra, require
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import models

RUN_CATEGORY = "regulation_review_run"
WORK_CATEGORY = "regulation_review_work"


class Resume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    facts: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    changed_requests: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dry_run: bool = False


class ProjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID


class Explain(ProjectRef):
    question: str = Field(min_length=1, max_length=2000)


class SaveWork(ProjectRef):
    title: str = Field(min_length=1, max_length=500)
    notes: str = Field(default="", max_length=10000)
    dry_run: bool = False


class SqlRunStore:
    """``RunStore`` on the entities table: one Document entity per run revision."""

    def __init__(self, factory: sessionmaker[Session], record_type: type) -> None:
        self._factory = factory
        self._record = record_type

    @staticmethod
    def _key(run_id: str, revision: int) -> str:
        return f"regulation-review-run:{run_id}:{revision}"

    def save(self, record) -> None:
        key = self._key(record.run_id, record.run_revision)
        properties = {
            "project_id": record.project_id,
            "run_id": record.run_id,
            "run_revision": record.run_revision,
            "idempotency_key": record.idempotency_key,
            "canonical": False,
            "record": record.model_dump(mode="json"),
        }
        with self._factory() as session:
            row = session.scalar(select(models.Entity).where(models.Entity.stable_key == key))
            if row is None:
                session.add(
                    models.Entity(
                        stable_key=key,
                        entity_type_id="Document",
                        name=f"규제 검토 실행 {record.run_id} rev {record.run_revision}",
                        category=RUN_CATEGORY,
                        properties=properties,
                    )
                )
            else:
                row.properties = properties
            session.commit()

    def _rows(self, session: Session, run_id: str):
        query = select(models.Entity).where(
            models.Entity.category == RUN_CATEGORY,
            models.Entity.properties["run_id"].as_string() == run_id,
        )
        return list(session.scalars(query))

    def load(self, run_id: str, revision: int | None = None):
        not_found = require("sion_regulation.review.runs", extra="regulation").RunNotFound
        with self._factory() as session:
            rows = {row.properties["run_revision"]: row for row in self._rows(session, run_id)}
            if not rows:
                raise not_found(run_id)
            chosen = max(rows) if revision is None else revision
            if chosen not in rows:
                raise not_found(f"{run_id}@{revision}")
            return self._record.model_validate(rows[chosen].properties["record"])

    def find_by_key(self, key: str):
        with self._factory() as session:
            rows = session.scalars(
                select(models.Entity).where(
                    models.Entity.category == RUN_CATEGORY,
                    models.Entity.properties["idempotency_key"].as_string() == key,
                )
            ).all()
            if not rows:
                return None
            newest = max(rows, key=lambda row: row.properties["run_revision"])
            return self._record.model_validate(newest.properties["record"])

    def revisions(self, run_id: str) -> list[int]:
        with self._factory() as session:
            return sorted(row.properties["run_revision"] for row in self._rows(session, run_id))


def build_workflow(factory: sessionmaker[Session]):
    """Workflow on the platform store, with the operator's bundle when one is configured."""

    review = require("sion_regulation.review.workflow", extra="regulation")
    runs = require("sion_regulation.review.runs", extra="regulation")
    bundles = require("sion_regulation.review.bundle", extra="regulation")
    path = os.getenv("SION_REGULATION_REVIEW_BUNDLE")
    bundle = bundles.load_bundle(Path(path)) if path else bundles.ReviewBundle()
    return review.ReviewWorkflow(
        bundle.catalog(),
        store=SqlRunStore(factory, runs.RunRecord),
        links=bundle.links,
        profile=bundle.profile,
        rules=bundle.rules,
        conditions=bundle.conditions,
        exception_facts=bundle.exception_facts,
        positions=bundle.positions,
        reviewed_relations=bundle.reviewed_relations,
        evidence=bundle.evidence,
    )


def register(app, factory: sessionmaker[Session], get_session, read, write):
    root = "/api/v1/regulation/reviews"
    app.state.regulation_review_flow = None

    def module(name: str):
        try:
            return require(f"sion_regulation.review.{name}", extra="regulation")
        except MissingExtra as exc:
            raise HTTPException(503, str(exc)) from exc

    def flow():
        if app.state.regulation_review_flow is None:
            try:
                app.state.regulation_review_flow = build_workflow(factory)
            except MissingExtra as exc:
                raise HTTPException(503, str(exc)) from exc
        return app.state.regulation_review_flow

    def parse_request(payload: dict[str, Any]):
        review = module("workflow")
        try:
            request = review.ReviewRequest.model_validate(payload)
        except ValueError as exc:
            raise HTTPException(422, "invalid review request") from exc
        refuse_collected_facts(request.facts)
        return request

    def refuse_collected_facts(facts) -> None:
        review = module("workflow")
        problems = review.client_fact_problems(facts)
        if problems:
            raise HTTPException(422, {"detail": "facts must be claims", "problems": problems})

    def require_project(session: Session, project_id: str | uuid.UUID) -> models.Entity:
        try:
            key = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        except ValueError as exc:
            raise HTTPException(404, "project not found") from exc
        project = session.get(models.Entity, key)
        if project is None or project.entity_type_id != "Project":
            raise HTTPException(404, "project not found")
        return project

    def guarded(call, *args, **kwargs):
        """Another project's run reads exactly like a run that does not exist."""

        try:
            return call(*args, **kwargs)
        except (PermissionError, KeyError) as exc:
            raise HTTPException(404, "review not found") from exc

    @app.post(root + "/plan", dependencies=[Depends(read)])
    def plan(payload: dict[str, Any], session=Depends(get_session)):
        request = parse_request(payload)
        require_project(session, request.proposal.project_id)
        try:
            return flow().plan_review(request)
        except ValueError as exc:
            raise HTTPException(422, "invalid review request") from exc

    @app.post(root, dependencies=[Depends(write)])
    def start(payload: dict[str, Any], dry_run: bool = False, session=Depends(get_session)):
        request = parse_request(payload)
        require_project(session, request.proposal.project_id)
        conflict = module("runs").IdempotencyConflict
        try:
            if dry_run:
                return {"dry_run": True, "saved": False, "plan": flow().plan_review(request)}
            return flow().start_review(request)
        except conflict as exc:
            raise HTTPException(409, "idempotency key reused with a different payload") from exc
        except ValueError as exc:
            raise HTTPException(422, "invalid review request") from exc

    @app.get(root + "/basis/{evidence_id}", dependencies=[Depends(read)])
    def basis(evidence_id: str, project_id: uuid.UUID):
        return guarded(flow().get_basis, evidence_id, project_id=str(project_id))

    @app.get(root + "/works/{work_id}", dependencies=[Depends(read)])
    def read_work(work_id: uuid.UUID, project_id: uuid.UUID, session=Depends(get_session)):
        return work_output(saved_work(session, work_id, project_id))

    @app.get(
        root + "/works/{work_id}/briefing",
        response_class=PlainTextResponse,
        dependencies=[Depends(read)],
    )
    def work_briefing(work_id: uuid.UUID, project_id: uuid.UUID, session=Depends(get_session)):
        row = saved_work(session, work_id, project_id)
        render = module("workflow").render_briefing
        return render(row.properties["output"])

    @app.get(root + "/{run_id}", dependencies=[Depends(read)])
    def get_review(run_id: str, project_id: uuid.UUID, revision: int | None = Query(None, ge=1)):
        return guarded(flow().get_review, run_id, project_id=str(project_id), revision=revision)

    @app.get(root + "/{run_id}/briefing", response_class=PlainTextResponse, dependencies=[Depends(read)])
    def get_briefing(run_id: str, project_id: uuid.UUID, revision: int | None = Query(None, ge=1)):
        return guarded(flow().briefing, run_id, project_id=str(project_id), revision=revision)

    @app.get(root + "/{run_id}/compare", dependencies=[Depends(read)])
    def compare(
        run_id: str,
        project_id: uuid.UUID,
        to: str,
        revision: int | None = Query(None, ge=1),
        to_revision: int | None = Query(None, ge=1),
    ):
        return guarded(
            flow().compare,
            run_id,
            to,
            project_id=str(project_id),
            revision_a=revision,
            revision_b=to_revision,
        )

    @app.post(root + "/{run_id}/explain", dependencies=[Depends(read)])
    def explain(run_id: str, payload: Explain):
        return guarded(flow().explain, run_id, payload.question, project_id=str(payload.project_id))

    @app.post(root + "/{run_id}/cancel", dependencies=[Depends(write)])
    def cancel(run_id: str, payload: ProjectRef):
        return guarded(flow().cancel_review, run_id, project_id=str(payload.project_id))

    @app.post(root + "/{run_id}/resume", dependencies=[Depends(write)])
    def resume(run_id: str, payload: Resume):
        model = module("model")
        project = str(payload.project_id)
        if payload.dry_run:
            current = guarded(flow().get_review, run_id, project_id=project)
            return {"dry_run": True, "saved": False, "next_revision": current["run_revision"] + 1}
        try:
            facts = [model.Fact.model_validate(item) for item in payload.facts]
        except ValueError as exc:
            raise HTTPException(422, "invalid supplementary fact") from exc
        refuse_collected_facts(facts)
        try:
            return guarded(
                flow().resume_review,
                run_id,
                project_id=project,
                supplement=facts,
                changed_requests=payload.changed_requests,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def work_output(row: models.Entity) -> dict[str, Any]:
        return {"id": str(row.id), "title": row.name, **row.properties}

    def saved_work(session: Session, work_id: uuid.UUID, project_id: uuid.UUID) -> models.Entity:
        row = session.get(models.Entity, work_id)
        valid = row is not None and row.category == WORK_CATEGORY
        if not valid or row.properties["project_id"] != str(project_id):
            raise HTTPException(404, "review work not found")
        return row

    @app.post(root + "/{run_id}/works", dependencies=[Depends(write)])
    def save_work(run_id: str, payload: SaveWork, session=Depends(get_session)):
        """Save the server-owned output and prove it by reading the row back."""

        project = require_project(session, payload.project_id)
        project_id = str(payload.project_id)
        try:
            receipt = guarded(flow().save_work, run_id, project_id=project_id, notes=payload.notes)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        output = guarded(flow().get_review, run_id, project_id=project_id)
        key = f"regulation-review-work:{project_id}:{run_id}:{receipt.run_revision}"
        if payload.dry_run:
            return {"dry_run": True, "saved": False, "receipt": receipt.model_dump(mode="json")}

        existing = session.scalar(select(models.Entity).where(models.Entity.stable_key == key))
        if existing is None:
            row = models.Entity(
                stable_key=key,
                entity_type_id="Document",
                name=payload.title,
                category=WORK_CATEGORY,
                properties={
                    "project_id": project_id,
                    "run_id": run_id,
                    "run_revision": receipt.run_revision,
                    "digest": receipt.digest,
                    "notes": payload.notes,
                    "output": output,
                    "canonical": False,
                },
            )
            session.add(row)
            session.flush()
            session.add(
                models.Relation(
                    stable_key=key + ":project",
                    source_entity_id=row.id,
                    target_entity_id=project.id,
                    relation_type_id="PART_OF",
                    verification_state="unverified",
                    source_kind="regulation_review",
                    properties={"canonical": False},
                )
            )
            session.commit()
            existing = row
        elif existing.properties["digest"] != receipt.digest:
            raise HTTPException(409, "saved work differs from the stored run output")

        session.expire_all()
        stored = session.get(models.Entity, existing.id)
        digest = module("model").canonical_digest
        if stored is None or digest(stored.properties["output"]) != receipt.digest:
            raise HTTPException(500, "saved work failed read-back verification")
        if not flow().verify_receipt(receipt):
            raise HTTPException(500, "run revision failed read-back verification")
        return {
            "saved": True,
            "verified": True,
            "work_id": str(stored.id),
            "receipt": receipt.model_dump(mode="json"),
        }
