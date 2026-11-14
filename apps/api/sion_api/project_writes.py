"""Project-scoped writes: upload documents into a project and edit the project's entities.

Project-restricted callers (signed-in users, project tokens) may only write inside the
projects on their ACL. Membership follows the read side (:func:`repository.in_projects`):
an entity belongs to a project when it is the Project entity itself or its
``properties.project_id`` names it. Denials answer 404 so nothing outside the ACL can be
probed.

Uploads are sent as the raw request body (``Content-Type`` is ignored) with the file name in
the ``filename`` query parameter, so no multipart parser is needed and the size limit is
enforced while the body streams in.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import models, repository, schemas
from .auth import (
    normalize_project_id,
    allowed_projects,
    current_principal,
    require_project_access,
    require_project_write,
    writable_projects,
)
from .config import PROJECT_ROOT

DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
FILENAME_LIMIT = 200
_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]+")


@dataclass(frozen=True)
class UploadSettings:
    root: Path
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES

    @classmethod
    def from_env(cls) -> "UploadSettings":
        root = Path(os.getenv("SION_UPLOAD_ROOT", "").strip() or PROJECT_ROOT / "runtime" / "uploads")
        raw = os.getenv("SION_UPLOAD_MAX_BYTES", "").strip()
        try:
            max_bytes = int(raw) if raw else DEFAULT_MAX_UPLOAD_BYTES
        except ValueError as exc:
            raise RuntimeError("SION_UPLOAD_MAX_BYTES must be an integer") from exc
        if max_bytes <= 0:
            raise RuntimeError("SION_UPLOAD_MAX_BYTES must be positive")
        return cls(root=root.resolve(), max_bytes=max_bytes)


class EntityUpdate(BaseModel):
    """Partial entity edit. ``properties`` is a JSON merge patch: ``null`` removes a key."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    category: str | None = Field(default=None, max_length=100)
    properties: dict[str, Any] | None = None


def safe_filename(raw: str) -> str:
    name = _UNSAFE.sub("_", Path(raw.replace("\\", "/")).name).strip(" .")
    if not name or name.startswith("."):
        raise HTTPException(status_code=422, detail="a file name with an extension is required")
    stem, dot, suffix = name.rpartition(".")
    if len(name) > FILENAME_LIMIT:
        name = f"{stem[: FILENAME_LIMIT - len(suffix) - 1]}{dot}{suffix}"
    return name


def _project_or_404(
    session: Session, request: Request, project_id: uuid.UUID, *, write: bool = False
) -> models.Entity:
    require_project_access(request, project_id)
    project = session.get(models.Entity, project_id)
    if project is None or project.entity_type_id != "Project":
        raise HTTPException(status_code=404, detail="project not found")
    if write:
        require_project_write(request, project_id)
    return project


def _visible_entity(
    session: Session, request: Request, entity_id: uuid.UUID, *, write: bool = False
) -> models.Entity:
    row = session.scalar(
        select(models.Entity).where(
            models.Entity.id == entity_id, repository.in_projects(allowed_projects(request))
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="entity not found")
    if write and not _in(session, models.Entity.id == entity_id, repository.in_projects(writable_projects(request))):
        raise HTTPException(status_code=403, detail="read-only access to this project")
    return row


def _in(session: Session, *conditions) -> bool:
    return session.scalar(select(models.Entity.id).where(*conditions)) is not None


def check_entity_create(request: Request, payload: schemas.EntityCreate) -> None:
    """A restricted caller may only add entities to one of its projects, never a new project."""
    if allowed_projects(request) is None:
        return
    if payload.entity_type_id == "Project":
        raise HTTPException(status_code=403, detail="creating projects requires an unrestricted token")
    project_id = (payload.properties or {}).get("project_id")
    if project_id is None:
        raise HTTPException(status_code=422, detail="properties.project_id is required for project-restricted callers")
    require_project_write(request, project_id)


def check_artifact_create(request: Request, payload: schemas.ArtifactCreate) -> None:
    """A restricted caller may only register artifacts in a project it can write."""
    if allowed_projects(request) is None:
        return
    project_id = (payload.properties or {}).get("project_id")
    if project_id is None:
        raise HTTPException(status_code=422, detail="properties.project_id is required for project-restricted callers")
    require_project_write(request, project_id)
    payload.properties["project_id"] = normalize_project_id(project_id)  # stored in the ACL's canonical form


def check_entities_visible(
    session: Session, request: Request, *entity_ids: uuid.UUID | None, write: bool = False
) -> None:
    """404 unless every entity is visible; with ``write`` also 403 unless it is writable."""
    projects = allowed_projects(request)
    if projects is None:
        return
    for entity_id in entity_ids:
        if entity_id is not None:
            _visible_entity(session, request, entity_id, write=write)


def check_relation_visible(
    session: Session, request: Request, relation_id: uuid.UUID | None, *, write: bool = False
) -> None:
    """404 unless both endpoints are visible; with ``write`` also 403 unless both are writable."""
    projects = allowed_projects(request)
    if projects is None or relation_id is None:
        return

    def inside(scope: frozenset[str] | None) -> bool:
        return session.scalar(
            select(models.Relation.id).where(
                models.Relation.id == relation_id, repository.relation_in_projects(scope)
            )
        ) is not None

    if not inside(projects):
        raise HTTPException(status_code=404, detail="relation not found")
    if write and not inside(writable_projects(request)):
        raise HTTPException(status_code=403, detail="read-only access to this project")


async def _receive_upload(request: Request, settings: UploadSettings, directory: Path) -> tuple[Path, str, int]:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > settings.max_bytes:
        raise HTTPException(status_code=413, detail=f"upload exceeds {settings.max_bytes} bytes")
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    handle = tempfile.NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False)
    tmp = Path(handle.name)
    try:
        with handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_bytes:
                    raise HTTPException(status_code=413, detail=f"upload exceeds {settings.max_bytes} bytes")
                digest.update(chunk)
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="empty upload")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, digest.hexdigest(), size


def _document_payload(row: models.Entity) -> dict:
    props = row.properties or {}
    return {
        "id": str(row.id),
        "name": row.name,
        "filename": props.get("path"),
        "byte_size": props.get("byte_size"),
        "sha256": props.get("upload_sha256"),
        "extractor": props.get("extractor"),
        "description": row.description,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def register(app, get_session, write_project, read_project) -> None:
    """``write_project`` / ``read_project`` are :func:`auth.project_scoped` scope dependencies."""
    app.state.upload_settings = UploadSettings.from_env()

    @app.post(
        "/api/v1/projects/{project_id}/documents",
        status_code=201,
        dependencies=[Depends(write_project)],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def upload_project_document(
        request: Request,
        project_id: uuid.UUID,
        filename: str = Query(min_length=1, max_length=1000, description="Original file name; its extension picks the parser"),
        session: Session = Depends(get_session),
    ):
        from sion_ingestion.document_ingest import DOCUMENT_SUFFIXES, document_stable_key, ingest_documents

        await run_in_threadpool(lambda: _project_or_404(session, request, project_id, write=True))
        name = safe_filename(filename)
        suffix = Path(name).suffix.lower()
        if suffix not in DOCUMENT_SUFFIXES:
            raise HTTPException(
                status_code=415,
                detail=f"unsupported document type {suffix or '(none)'}; allowed: {', '.join(sorted(DOCUMENT_SUFFIXES))}",
            )
        settings: UploadSettings = request.app.state.upload_settings
        project_dir = settings.root / str(project_id)
        tmp, sha256, size = await _receive_upload(request, settings, project_dir)
        # Content-addressed per project: the same bytes uploaded twice land on one path and
        # therefore one document entity (ingest skips existing stable keys).
        final_dir = project_dir / sha256[:32]
        final_dir.mkdir(parents=True, exist_ok=True)
        final = final_dir / name
        if final.exists():
            tmp.unlink(missing_ok=True)
        else:
            os.replace(tmp, final)

        def ingest() -> dict:
            result = ingest_documents(session, [final], project_id=str(project_id))
            document = session.scalar(
                select(models.Entity).where(models.Entity.stable_key == document_stable_key(final))
            )
            if document is not None and (document.properties or {}).get("upload_sha256") != sha256:
                document.properties = {**(document.properties or {}), "upload_sha256": sha256}
                session.commit()
            return {"result": result, "document": document}

        outcome = await run_in_threadpool(ingest)
        result = outcome["result"]
        document = outcome["document"]
        return {
            "project_id": str(project_id),
            "filename": name,
            "sha256": sha256,
            "byte_size": size,
            "document": _document_payload(document) if document is not None else None,
            # Server paths stay private: only the reasons are returned.
            "skipped": [item["reason"] for item in result["skipped"]],
            "created_nodes": result["created_nodes"],
            "created_edges": result["created_edges"],
            "skipped_nodes": result["skipped_nodes"],
            "evidence_created": result["evidence_created"],
            "verification_state": result["verification_state"],
        }

    @app.get("/api/v1/projects/{project_id}/documents", dependencies=[Depends(read_project)])
    def list_project_documents(
        request: Request,
        project_id: uuid.UUID,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        _project_or_404(session, request, project_id)
        rows = session.scalars(
            select(models.Entity)
            .where(
                models.Entity.entity_type_id == "Document",
                models.Entity.properties["project_id"].as_string() == str(project_id),
            )
            .order_by(models.Entity.updated_at.desc(), models.Entity.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return {"project_id": str(project_id), "items": [_document_payload(row) for row in rows]}

    @app.patch(
        "/api/v1/entities/{entity_id}",
        response_model=schemas.EntityRead,
        dependencies=[Depends(write_project)],
    )
    def update_entity(
        request: Request,
        entity_id: uuid.UUID,
        payload: EntityUpdate,
        session: Session = Depends(get_session),
    ):
        row = _visible_entity(session, request, entity_id, write=True)
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] is None:
            raise HTTPException(status_code=422, detail="name cannot be null")
        patch = changes.pop("properties", None)
        if patch is not None:
            properties = dict(row.properties or {})
            if "project_id" in patch and patch["project_id"] != properties.get("project_id"):
                # Moving an entity between projects would let a member push data into, or pull
                # it out of, a project; only unrestricted callers may do that.
                if allowed_projects(request) is not None:
                    raise HTTPException(status_code=403, detail="project_id cannot be changed by project-restricted callers")
            for key, value in patch.items():
                if value is None:
                    properties.pop(key, None)
                else:
                    properties[key] = value
            subject = current_principal(request).subject
            if subject:
                properties["last_edited_by"] = subject
            row.properties = properties
        for key, value in changes.items():
            setattr(row, key, value)
        session.commit()
        session.refresh(row)
        return row
