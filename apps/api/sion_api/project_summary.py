"""Read-only, bounded per-project regulation work summary for mobile clients (Issue #71 step D).

``GET /api/v1/regulation/works`` returns whole saved reports. Mobile clients only need a
small per-project overview, so this route reads a handful of scalar columns, never the
stored report payload, and bounds page size, response size and request rate.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select

from . import models
from .auth import AuthPolicy

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_PROJECT_FILTER = 50
NAME_LIMIT = 200
DEFAULT_MAX_BYTES = 64 * 1024
MIN_MAX_BYTES = 4 * 1024
DEFAULT_RATE_LIMIT = (60, 60.0)
WORK_STATUSES = ("open", "in_review", "done")


class RateLimiter:
    """In-process sliding-window limiter keyed by client; not shared across workers."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        *,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0 and self.window_seconds > 0

    def check(self, key: str) -> float | None:
        """Record a hit; return ``None`` when allowed, else seconds until retry."""
        if not self.enabled:
            return None
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
                while len(self._hits) > self.max_clients:
                    self._hits.popitem(last=False)
            else:
                self._hits.move_to_end(key)
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return max(hits[0] + self.window_seconds - now, 0.0)
            hits.append(now)
            return None

    @classmethod
    def from_env(cls) -> "RateLimiter":
        """``SION_SUMMARY_RATE_LIMIT=<requests>/<seconds>``; ``0`` disables throttling."""
        raw = os.getenv("SION_SUMMARY_RATE_LIMIT", "").strip()
        if not raw:
            return cls(*DEFAULT_RATE_LIMIT)
        if raw == "0":
            return cls(0, 0)
        count, _, window = raw.partition("/")
        try:
            limiter = cls(int(count), float(window or 60))
        except ValueError as exc:
            raise RuntimeError("SION_SUMMARY_RATE_LIMIT must look like '60/60' (requests/seconds) or '0'") from exc
        if limiter.max_requests < 0 or limiter.window_seconds <= 0:
            raise RuntimeError("SION_SUMMARY_RATE_LIMIT must use a non-negative count and a positive window")
        return limiter


@dataclass(frozen=True)
class SummaryLimits:
    max_bytes: int = DEFAULT_MAX_BYTES

    @classmethod
    def from_env(cls) -> "SummaryLimits":
        raw = os.getenv("SION_SUMMARY_MAX_BYTES", "").strip()
        if not raw:
            return cls()
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError("SION_SUMMARY_MAX_BYTES must be an integer") from exc
        return cls(max_bytes=max(value, MIN_MAX_BYTES))


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= NAME_LIMIT else text[: NAME_LIMIT - 1] + "…"


def register(app, get_session, policy: AuthPolicy, read) -> None:
    app.state.summary_rate_limiter = RateLimiter.from_env()
    app.state.summary_limits = SummaryLimits.from_env()

    def throttle(request: Request, _authorized: None = Depends(read)) -> None:
        # Runs after scope checks so keys come only from accepted tokens or trusted local peers.
        retry_after = request.app.state.summary_rate_limiter.check(policy.client_key(request))
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail="summary rate limit exceeded",
                headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
            )

    def project_scope(request: Request, project_id: list[uuid.UUID] | None = Query(default=None)) -> list[str] | None:
        """Resolve the project filter against the token's project ACL before any session opens."""
        requested = sorted({str(pid) for pid in project_id or []})
        if len(requested) > MAX_PROJECT_FILTER:
            raise HTTPException(422, f"at most {MAX_PROJECT_FILTER} project_id filters are allowed")
        allowed = policy.allowed_projects(request)
        if allowed is None:
            return requested or None
        if any(pid not in allowed for pid in requested):
            raise HTTPException(403, "project not permitted for this token")
        return requested or sorted(allowed)

    @app.get("/api/v1/regulation/summary", dependencies=[Depends(throttle)])
    def project_summary(
        request: Request,
        scope: list[str] | None = Depends(project_scope),
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: uuid.UUID | None = None,
        session=Depends(get_session),
    ):
        query = select(models.Entity.id, models.Entity.name).where(models.Entity.entity_type_id == "Project")
        if scope is not None:
            if not scope:
                return _envelope([], False, limit, request.app.state.summary_limits.max_bytes)
            query = query.where(models.Entity.id.in_([uuid.UUID(pid) for pid in scope]))
        if cursor is not None:
            query = query.where(models.Entity.id > cursor)
        projects = session.execute(query.order_by(models.Entity.id).limit(limit + 1)).all()
        has_more = len(projects) > limit
        projects = projects[:limit]

        ids = [str(row.id) for row in projects]
        works: dict[str, list] = {pid: [] for pid in ids}
        if ids:
            props = models.Entity.properties
            work_rows = session.execute(
                select(
                    models.Entity.id,
                    models.Entity.name,
                    models.Entity.updated_at,
                    props["project_id"].as_string().label("project_id"),
                    props["status"].as_string().label("status"),
                    props[("report", "decision", "status")].as_string().label("decision_status"),
                    props[("report", "as_of")].as_string().label("as_of"),
                )
                .where(models.Entity.category == "regulation_work")
                .where(props["project_id"].as_string().in_(ids))
                .order_by(models.Entity.updated_at.desc(), models.Entity.id)
            ).all()
            for row in work_rows:
                works.setdefault(row.project_id, []).append(row)

        items = []
        for project in projects:
            rows = works.get(str(project.id), [])
            counts = {status: 0 for status in WORK_STATUSES}
            for row in rows:
                key = row.status if row.status in counts else "other"
                counts[key] = counts.get(key, 0) + 1
            latest = rows[0] if rows else None
            items.append(
                {
                    "project_id": str(project.id),
                    "project_name": _clip(project.name),
                    "work_count": len(rows),
                    "status_counts": counts,
                    "latest_work": (
                        {
                            "id": str(latest.id),
                            "title": _clip(latest.name),
                            "status": _clip(latest.status),
                            "decision_status": _clip(latest.decision_status),
                            "as_of": _clip(latest.as_of),
                            "updated_at": latest.updated_at.isoformat() if latest.updated_at else None,
                        }
                        if latest
                        else None
                    ),
                }
            )
        return _envelope(items, has_more, limit, request.app.state.summary_limits.max_bytes)


def _envelope(items: list[dict], has_more: bool, limit: int, max_bytes: int) -> dict:
    body = {
        "read_only": True,
        "canonical": False,
        "limit": limit,
        "max_bytes": max_bytes,
        "items": [],
        "next_cursor": None,
        "truncated": False,
    }
    budget = max_bytes - _size({**body, "next_cursor": str(uuid.UUID(int=0))})
    kept: list[dict] = []
    used = 0
    for item in items:
        cost = _size(item) + 2
        if kept and used + cost > budget:
            body["truncated"] = True
            break
        kept.append(item)
        used += cost
    body["items"] = kept
    if kept and (has_more or body["truncated"]):
        body["next_cursor"] = kept[-1]["project_id"]
    return body
