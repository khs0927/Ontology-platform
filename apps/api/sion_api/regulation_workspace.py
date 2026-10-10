"""Saved regulation reviews in the canonical project workspace; reports remain advisory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sion_core.contracts import validate
from sqlalchemy import select

from . import models

TaskText = Annotated[str, Field(min_length=1, max_length=1000)]


class WorkSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    run_id: uuid.UUID
    notes: str = Field(default="", max_length=10000)
    tasks: list[TaskText] = Field(default_factory=list, max_length=100)
    dry_run: bool = False


class WorkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = Field(max_length=10000)
    tasks: list[TaskText] = Field(max_length=100)
    status: Literal["open", "in_review", "done"] = "open"
    dry_run: bool = False


def briefing(report: dict, notes: str = "", tasks: list[str] | None = None) -> str:
    statuses = {
        "insufficient_evidence": "근거 부족 · 판단 보류",
        "conflicting_evidence": "근거 충돌 · 판단 보류",
        "outside_scope": "검토 범위 밖",
        "permitted": "검토된 규칙 범위에서 적합",
        "conditionally_permitted": "검토된 규칙 범위에서 조건부 적합",
        "not_permitted": "검토된 규칙 범위에서 부적합",
    }
    lines = [
        "# 건축 법규 검토 브리핑",
        "",
        f"기준일: {report['as_of']}",
        f"검토 결과: {statuses.get(report['decision']['status'], report['decision']['status'])}",
        "",
        "## 검토 보류·충돌 사항",
    ]
    reasons = {"REVIEWED_RULE_SET_NOT_CONFIGURED": "적용 범위가 검토된 규칙 묶음이 연결되지 않았습니다."}
    lines.extend(f"- {reasons.get(x, x)} ({x})" for x in report["decision"]["reason_codes"])
    lines.extend(["", "## 법규 및 출처"])
    for branch, result in report["results"].items():
        lines.append(f"\n### {branch} ({result['status']})")
        if result.get("reason"):
            lines.append(f"수집 상태: {result['reason']}")
        documents = {}
        for ev in result.get("evidence", []):
            documents.setdefault((ev["document_id"], ev["source_url"]), []).append(ev)
        for (_, url), evidence in documents.items():
            first = evidence[0]
            lines.extend(
                [
                    f"\n#### {first.get('document_title') or first['document_id']}",
                    f"출처: {url}",
                    f"시행일: {first.get('effective_from') or '미확인'} / 수집 근거: {len(evidence)}건",
                    f"원문 해시: {first['snapshot_hash']}",
                ]
            )
            for ev in evidence:
                location = ev.get("location", {})
                # Overview snapshots contain metadata; brief the located clauses instead.
                if not location and len(evidence) > 1:
                    continue
                heading = re.search(r"제\d+조(?:의\d+)?\([^\n)]*\)", ev["excerpt"])
                title = heading.group() if heading else location.get("title") or ev["claim"]
                meaningful = [
                    line.strip()
                    for line in ev["excerpt"].splitlines()
                    if re.search(r"[가-힣]{2}", line) and not line.strip().startswith("[본조신설")
                ]
                excerpt = " ".join(meaningful)
                excerpt = excerpt[:280] + ("…" if len(excerpt) > 280 else "")
                lines.extend([f"- **{title}** (근거 {ev['evidence_id']})", f"  원문 발췌: {excerpt}"])
    lines.extend(
        ["", "발췌는 읽기 편하도록 줄인 원문입니다. 전체 근거와 원문 위치는 저장된 검토 보고서에 남아 있습니다."]
    )
    lines.extend(["", "## 작업 메모", notes, "", "## 후속 작업"])
    lines.extend(f"- [ ] {task}" for task in tasks or [])
    lines.extend(["", "이 자료는 검토 근거이며, 확정된 허가 또는 온톨로지 사실로 자동 승격되지 않습니다."])
    return "\n".join(lines)


def register(app, get_session, read, write, client=None):
    @app.get("/regulation", response_class=HTMLResponse, dependencies=[Depends(read)])
    def workspace():
        return Path(__file__).with_name("regulation_workspace.html").read_text(encoding="utf-8")

    async def gateway(path, body=None):
        base = os.getenv("SION_REGULATION_GATEWAY_URL", "").rstrip("/")
        if not base:
            raise HTTPException(503, "SION_REGULATION_GATEWAY_URL is not configured")
        token = os.getenv("GATEWAY_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(timeout=65, transport=client) as http:
                response = await (
                    http.get(base + path, headers=headers)
                    if body is None
                    else http.post(base + path, json=body, headers=headers)
                )
            if response.status_code >= 400:
                raise HTTPException(502, f"regulation gateway returned HTTP {response.status_code}")
            report = response.json()
            validate("building-regulation-report/1", report)
            return report
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, ImportError) as exc:
            raise HTTPException(502, "regulation gateway unavailable or report contract invalid") from exc

    def work(session, work_id):
        row = session.get(models.Entity, work_id)
        if row is None or row.category != "regulation_work":
            raise HTTPException(404, "regulation work not found")
        return row

    def output(row):
        return {"id": str(row.id), "title": row.name, **row.properties}

    @app.post("/api/v1/regulation/gateway/report", dependencies=[Depends(read)])
    async def report(payload: dict):
        return {"canonical": False, "report": await gateway("/api/v1/produce-compliance-report", payload)}

    @app.post("/api/v1/regulation/works", dependencies=[Depends(write)])
    async def save(payload: WorkSave, session=Depends(get_session)):
        project = session.get(models.Entity, payload.project_id)
        if project is None or project.entity_type_id != "Project":
            raise HTTPException(404, "project not found")
        # Accept only a server-owned audit run, never a caller-supplied report.
        report = await gateway(f"/api/v1/audit/{payload.run_id}")
        if report["request_id"] != str(payload.run_id):
            raise HTTPException(502, "audit run identity mismatch")
        key = f"regulation-work:{payload.project_id}:{payload.run_id}"
        existing = session.scalar(select(models.Entity).where(models.Entity.stable_key == key))
        if existing:
            return {"saved": True, "existing": True, "work": output(existing)}
        if payload.dry_run:
            return {
                "saved": False,
                "dry_run": True,
                "project_id": str(payload.project_id),
                "run_id": str(payload.run_id),
                "briefing": briefing(report, payload.notes, payload.tasks),
            }
        props = {
            "project_id": str(payload.project_id),
            "run_id": str(payload.run_id),
            "canonical": False,
            "report": report,
            "notes": payload.notes,
            "tasks": payload.tasks,
            "status": "open",
        }
        row = models.Entity(
            stable_key=key, entity_type_id="Document", name=payload.title, category="regulation_work", properties=props
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
                source_kind="regulation_gateway",
                properties={"canonical": False},
            )
        )
        for result in report["results"].values():
            for ev in result.get("evidence", []):
                session.add(
                    models.Evidence(
                        entity_id=row.id,
                        source_uri=ev["source_url"],
                        source_locator=json.dumps(ev.get("location", {}), ensure_ascii=False),
                        excerpt_hash="sha256:" + hashlib.sha256(ev["excerpt"].encode()).hexdigest(),
                        verification_state="unverified",
                        extractor="building-regulation-gateway",
                        properties={**ev, "canonical": False},
                    )
                )
        session.commit()
        return {"saved": True, "work": output(row)}

    @app.get("/api/v1/regulation/works", dependencies=[Depends(read)])
    def list_works(
        project_id: uuid.UUID | None = None, limit: int = Query(50, ge=1, le=200), session=Depends(get_session)
    ):
        query = select(models.Entity).where(models.Entity.category == "regulation_work")
        if project_id:
            query = query.where(models.Entity.properties["project_id"].as_string() == str(project_id))
        return [output(row) for row in session.scalars(query.order_by(models.Entity.created_at.desc()).limit(limit))]

    @app.get("/api/v1/regulation/works/{work_id}", dependencies=[Depends(read)])
    def get_work(work_id: uuid.UUID, session=Depends(get_session)):
        return output(work(session, work_id))

    @app.post("/api/v1/regulation/works/{work_id}", dependencies=[Depends(write)])
    def update(work_id: uuid.UUID, payload: WorkUpdate, session=Depends(get_session)):
        row = work(session, work_id)
        if payload.dry_run:
            return {"saved": False, "dry_run": True, "changes": payload.model_dump(exclude={"dry_run"})}
        row.properties = {**row.properties, **payload.model_dump(exclude={"dry_run"})}
        session.commit()
        return {"saved": True, "work": output(row)}

    @app.get(
        "/api/v1/regulation/works/{work_id}/briefing", response_class=PlainTextResponse, dependencies=[Depends(read)]
    )
    def get_briefing(work_id: uuid.UUID, session=Depends(get_session)):
        props = work(session, work_id).properties
        return briefing(props["report"], props["notes"], props["tasks"])
