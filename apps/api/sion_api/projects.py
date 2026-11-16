"""Projects for signed-in users: create, list, members and one-time invitations.

The identity provider (Supabase Auth by default) only proves who a user is. Which projects a
user may read or write is stored here (``project_members``) and merged into the caller's
project ACL on every request (:class:`MembershipResolver`, installed on
``AuthPolicy.memberships``). Roles:

- ``owner``: everything an editor can do, plus inviting, changing roles and removing members.
- ``editor``: read and write the project's knowledge.
- ``viewer``: read only.

Invitations are one-time tokens (shown once, stored as SHA-256) with an expiry, a role and an
optional email binding; the owner shares the link themselves, so no mail provider is needed.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models
from .auth import current_principal, require_project_access
from .db import Base

ROLES = ("owner", "editor", "viewer")
INVITE_ROLES = ("editor", "viewer")
MEMBERSHIP_TTL_SECONDS = 30.0
DEFAULT_MAX_OWNED_PROJECTS = 10
MAX_INVITE_DAYS = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_project_member_role"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    user_subject: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    added_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ProjectInvite(Base):
    __tablename__ = "project_invites"
    __table_args__ = (CheckConstraint("role IN ('editor', 'viewer')", name="ck_project_invite_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MembershipResolver:
    """``subject -> {project_id: role}`` from ``project_members`` (cached briefly).

    Errors resolve to no memberships, so a database hiccup can only hide projects for a
    moment, never grant them. Every membership change calls :meth:`forget`.
    """

    def __init__(self, session_factory, ttl: float = MEMBERSHIP_TTL_SECONDS):
        self.session_factory = session_factory
        self.ttl = ttl
        self._cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._lock = threading.Lock()

    def __call__(self, subject: str) -> dict[str, str]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(subject)
            if hit is not None and now - hit[0] < self.ttl:
                return hit[1]
        try:
            with self.session_factory() as session:
                rows = session.execute(
                    select(ProjectMember.project_id, ProjectMember.role).where(ProjectMember.user_subject == subject)
                ).all()
        except Exception:  # noqa: BLE001 - fail closed on any lookup error
            return {}
        roles = {str(row.project_id): row.role for row in rows if row.role in ROLES}
        with self._lock:
            self._cache[subject] = (now, roles)
        return roles

    def forget(self, subject: str | None = None) -> None:
        with self._lock:
            if subject is None:
                self._cache.clear()
            else:
                self._cache.pop(subject, None)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(default="editor", pattern="^(editor|viewer)$")
    email: str | None = Field(default=None, max_length=320, description="Only this signed-in email may accept")
    expires_in_days: int = Field(default=7, ge=1, le=MAX_INVITE_DAYS)


class InviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern="^(owner|editor|viewer)$")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _max_owned() -> int:
    raw = os.getenv("SION_MAX_OWNED_PROJECTS", "").strip()
    try:
        return int(raw) if raw else DEFAULT_MAX_OWNED_PROJECTS
    except ValueError as exc:
        raise RuntimeError("SION_MAX_OWNED_PROJECTS must be an integer") from exc


def _signed_in(request: Request):
    principal = current_principal(request)
    if principal.kind != "user" or not principal.subject:
        raise HTTPException(status_code=403, detail="this action needs a signed-in user")
    return principal


def _member_payload(row: ProjectMember) -> dict:
    return {
        "subject": row.user_subject,
        "email": row.email,
        "role": row.role,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _invite_payload(row: ProjectInvite) -> dict:
    now = _utcnow()
    state = (
        "revoked" if row.revoked_at else "accepted" if row.accepted_at else "expired" if _aware(row.expires_at) <= now else "pending"
    )
    return {
        "id": str(row.id),
        "role": row.role,
        "email": row.email,
        "state": state,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": _aware(row.expires_at).isoformat(),
    }


def register(app, get_session, read_project, write_project, read_any, resolver: MembershipResolver | None) -> None:
    """``read_project``/``write_project`` are project-scoped scope dependencies; ``read_any``
    is a project-scoped ``read:knowledge`` dependency for routes open to users without projects."""

    def forget(subject: str | None) -> None:
        if resolver is not None and subject:
            resolver.forget(subject)

    def project_or_404(session: Session, request: Request, project_id: uuid.UUID) -> models.Entity:
        require_project_access(request, project_id)
        project = session.get(models.Entity, project_id)
        if project is None or project.entity_type_id != "Project":
            raise HTTPException(status_code=404, detail="project not found")
        return project

    def require_owner(session: Session, request: Request, project_id: uuid.UUID) -> models.Entity:
        project = project_or_404(session, request, project_id)
        principal = current_principal(request)
        if principal.projects is None:
            return project  # unrestricted callers (operators) manage every project
        if principal.role_in(project_id) != "owner":
            raise HTTPException(status_code=403, detail="only project owners can manage members")
        return project

    def owners(session: Session, project_id: uuid.UUID) -> int:
        return session.scalar(
            select(func.count()).select_from(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.role == "owner"
            )
        ) or 0

    @app.post("/api/v1/projects", status_code=201, dependencies=[Depends(write_project)])
    def create_project(request: Request, payload: ProjectCreate, session: Session = Depends(get_session)):
        """Create a project owned by the signed-in caller (needs ``write:knowledge``, e.g. a paid plan)."""
        principal = _signed_in(request)
        owned = session.scalar(
            select(func.count()).select_from(ProjectMember).where(
                ProjectMember.user_subject == principal.subject, ProjectMember.role == "owner"
            )
        ) or 0
        if owned >= _max_owned():
            raise HTTPException(status_code=409, detail=f"you already own {owned} projects (limit {_max_owned()})")
        project_id = uuid.uuid4()
        project = models.Entity(
            id=project_id,
            stable_key=f"project:{project_id}",
            entity_type_id="Project",
            name=payload.name.strip(),
            description=(payload.description or "").strip() or None,
            category="project",
            properties={"created_by": principal.subject},
        )
        session.add(project)
        session.flush()
        session.add(
            ProjectMember(
                project_id=project_id,
                user_subject=principal.subject,
                role="owner",
                email=principal.email,
                added_by=principal.subject,
            )
        )
        session.commit()
        forget(principal.subject)
        return {"id": str(project_id), "name": project.name, "description": project.description, "role": "owner"}

    @app.get("/api/v1/projects", dependencies=[Depends(read_any)])
    def list_projects(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        session: Session = Depends(get_session),
    ):
        """Projects the caller can see, with the caller's role (``null`` for claim-granted access)."""
        principal = current_principal(request)
        query = select(models.Entity).where(models.Entity.entity_type_id == "Project")
        if principal.projects is not None:
            if not principal.projects:
                return {"items": []}
            query = query.where(models.Entity.id.in_([uuid.UUID(p) for p in principal.projects]))
        rows = session.scalars(query.order_by(models.Entity.name, models.Entity.id).limit(limit)).all()
        roles = dict(principal.roles)
        return {
            "items": [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "description": row.description,
                    "role": roles.get(str(row.id)),
                    "can_write": principal.can_write_project(row.id),
                }
                for row in rows
            ]
        }

    @app.get("/api/v1/projects/{project_id}/members", dependencies=[Depends(read_project)])
    def list_members(request: Request, project_id: uuid.UUID, session: Session = Depends(get_session)):
        project_or_404(session, request, project_id)
        rows = session.scalars(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at, ProjectMember.user_subject)
        ).all()
        return {"project_id": str(project_id), "items": [_member_payload(row) for row in rows]}

    @app.patch("/api/v1/projects/{project_id}/members/{subject}", dependencies=[Depends(write_project)])
    def change_role(
        request: Request,
        project_id: uuid.UUID,
        subject: str,
        payload: RoleChange,
        session: Session = Depends(get_session),
    ):
        require_owner(session, request, project_id)
        row = session.get(ProjectMember, (project_id, subject))
        if row is None:
            raise HTTPException(status_code=404, detail="member not found")
        if row.role == "owner" and payload.role != "owner" and owners(session, project_id) <= 1:
            raise HTTPException(status_code=409, detail="a project needs at least one owner")
        row.role = payload.role
        row.updated_at = _utcnow()
        session.commit()
        forget(subject)
        return _member_payload(row)

    @app.delete("/api/v1/projects/{project_id}/members/{subject}", dependencies=[Depends(write_project)])
    def remove_member(request: Request, project_id: uuid.UUID, subject: str, session: Session = Depends(get_session)):
        """Owners remove anyone; every member may remove themselves (leave)."""
        principal = current_principal(request)
        project_or_404(session, request, project_id)
        if principal.subject != subject:
            require_owner(session, request, project_id)
        row = session.get(ProjectMember, (project_id, subject))
        if row is None:
            raise HTTPException(status_code=404, detail="member not found")
        if row.role == "owner" and owners(session, project_id) <= 1:
            raise HTTPException(status_code=409, detail="a project needs at least one owner")
        session.delete(row)
        session.commit()
        forget(subject)
        return {"removed": subject}

    @app.post("/api/v1/projects/{project_id}/invites", status_code=201, dependencies=[Depends(write_project)])
    def create_invite(
        request: Request, project_id: uuid.UUID, payload: InviteCreate, session: Session = Depends(get_session)
    ):
        """One-time invitation. The token is returned once and never stored in clear text."""
        require_owner(session, request, project_id)
        principal = current_principal(request)
        token = secrets.token_urlsafe(32)
        row = ProjectInvite(
            project_id=project_id,
            token_sha256=token_digest(token),
            role=payload.role,
            email=(payload.email or "").strip().lower() or None,
            created_by=principal.subject or principal.kind,
            expires_at=_utcnow() + timedelta(days=payload.expires_in_days),
        )
        session.add(row)
        session.commit()
        return {**_invite_payload(row), "token": token}

    @app.get("/api/v1/projects/{project_id}/invites", dependencies=[Depends(read_project)])
    def list_invites(request: Request, project_id: uuid.UUID, session: Session = Depends(get_session)):
        require_owner(session, request, project_id)
        rows = session.scalars(
            select(ProjectInvite)
            .where(ProjectInvite.project_id == project_id)
            .order_by(ProjectInvite.created_at.desc())
            .limit(100)
        ).all()
        return {"project_id": str(project_id), "items": [_invite_payload(row) for row in rows]}

    @app.delete("/api/v1/projects/{project_id}/invites/{invite_id}", dependencies=[Depends(write_project)])
    def revoke_invite(
        request: Request, project_id: uuid.UUID, invite_id: uuid.UUID, session: Session = Depends(get_session)
    ):
        require_owner(session, request, project_id)
        row = session.get(ProjectInvite, invite_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(status_code=404, detail="invite not found")
        if row.accepted_at is None and row.revoked_at is None:
            row.revoked_at = _utcnow()
            session.commit()
        return _invite_payload(row)

    @app.post("/api/v1/invites/accept", dependencies=[Depends(read_any)])
    def accept_invite(request: Request, payload: InviteAccept, session: Session = Depends(get_session)):
        """Join a project with a one-time token. Every failure answers the same 404."""
        principal = _signed_in(request)
        row = session.scalar(select(ProjectInvite).where(ProjectInvite.token_sha256 == token_digest(payload.token)))
        unusable = (
            row is None
            or row.revoked_at is not None
            or row.accepted_at is not None
            or _aware(row.expires_at) <= _utcnow()
            or (row.email is not None and (principal.email or "").strip().lower() != row.email)
        )
        if unusable:
            raise HTTPException(status_code=404, detail="invitation not found or no longer valid")
        member = session.get(ProjectMember, (row.project_id, principal.subject))
        if member is None:
            member = ProjectMember(
                project_id=row.project_id,
                user_subject=principal.subject,
                role=row.role,
                email=principal.email,
                added_by=row.created_by,
            )
            session.add(member)
        elif ROLES.index(row.role) < ROLES.index(member.role):
            member.role = row.role  # an invitation can raise a role, never lower it
            member.updated_at = _utcnow()
        row.accepted_by = principal.subject
        row.accepted_at = _utcnow()
        session.commit()
        forget(principal.subject)
        project = session.get(models.Entity, row.project_id)
        return {"project_id": str(row.project_id), "name": project.name if project else None, "role": member.role}
