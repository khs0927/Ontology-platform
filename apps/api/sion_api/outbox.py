"""Transactional outbox for canonical Sion writes.

Every session created by :func:`sion_api.db.build_session_factory` uses
:class:`sion_api.db.SionSession`; its ``before_flush`` hook appends an
``OutboxEvent`` for each new entity / relation / evidence / artifact, each
relation invalidation and each entity update. The event rows are part of the
same flush and commit (or roll back) with the change.

Consumers pull with :func:`pending`, then :func:`acknowledge` or :func:`fail`
(exponential back-off). :func:`drain` runs a handler over pending events.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, attributes

from . import models

MAX_BACKOFF = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _s(value) -> str | None:
    return None if value is None else str(value)


def _payload(obj) -> tuple[str, dict]:
    if isinstance(obj, models.Entity):
        return "entity", {
            "stable_key": obj.stable_key,
            "entity_type_id": obj.entity_type_id,
            "name": obj.name,
            "category": obj.category,
        }
    if isinstance(obj, models.Relation):
        return "relation", {
            "stable_key": obj.stable_key,
            "relation_type_id": obj.relation_type_id,
            "source_entity_id": _s(obj.source_entity_id),
            "target_entity_id": _s(obj.target_entity_id),
            "verification_state": obj.verification_state,
            "valid_to": obj.valid_to.isoformat() if obj.valid_to else None,
        }
    if isinstance(obj, models.Evidence):
        return "evidence", {
            "entity_id": _s(obj.entity_id),
            "relation_id": _s(obj.relation_id),
            "source_uri": obj.source_uri,
            "verification_state": obj.verification_state,
        }
    if isinstance(obj, models.Artifact):
        return "artifact", {
            "stable_key": obj.stable_key,
            "storage_uri": obj.storage_uri,
            "content_hash": obj.content_hash,
        }
    raise TypeError(type(obj))


TRACKED = (models.Entity, models.Relation, models.Evidence, models.Artifact)


def _event(obj, event: str) -> models.OutboxEvent:
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    aggregate, payload = _payload(obj)
    return models.OutboxEvent(
        id=uuid.uuid4(),
        aggregate_type=aggregate,
        aggregate_id=obj.id,
        event_type=f"{aggregate}.{event}",
        payload=payload,
        attempts=0,
    )


def before_flush(session: Session, _flush_context, _instances) -> None:
    events: list[models.OutboxEvent] = []
    for obj in list(session.new):
        if isinstance(obj, TRACKED):
            events.append(_event(obj, "created"))
    for obj in list(session.dirty):
        if not isinstance(obj, TRACKED) or not session.is_modified(obj, include_collections=False):
            continue
        if isinstance(obj, models.Relation):
            history = attributes.get_history(obj, "valid_to")
            if history.added and history.added[0] is not None:
                events.append(_event(obj, "invalidated"))
                continue
        events.append(_event(obj, "updated"))
    for event in events:
        session.add(event)


def pending(session: Session, *, limit: int = 100, now: datetime | None = None) -> list[models.OutboxEvent]:
    now = now or _now()
    stmt = (
        select(models.OutboxEvent)
        .where(models.OutboxEvent.published_at.is_(None))
        .where(or_(models.OutboxEvent.next_attempt_at.is_(None), models.OutboxEvent.next_attempt_at <= now))
        .order_by(models.OutboxEvent.created_at, models.OutboxEvent.id)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def acknowledge(session: Session, ids: Iterable[uuid.UUID], *, consumer: str | None = None) -> int:
    rows = session.scalars(
        select(models.OutboxEvent).where(models.OutboxEvent.id.in_(list(ids)))
    ).all()
    count = 0
    for row in rows:
        if row.published_at is None:
            row.published_at = _now()
            row.consumer = consumer
            count += 1
    session.commit()
    return count


def fail(session: Session, event_id: uuid.UUID, error: str, *, base_delay: timedelta = timedelta(seconds=5)) -> models.OutboxEvent | None:
    row = session.get(models.OutboxEvent, event_id)
    if row is None or row.published_at is not None:
        return row
    row.attempts += 1
    row.last_error = error[:2000]
    row.next_attempt_at = _now() + min(base_delay * (2 ** (row.attempts - 1)), MAX_BACKOFF)
    session.commit()
    return row


def drain(
    session: Session,
    handler: Callable[[models.OutboxEvent], None],
    *,
    limit: int = 100,
    consumer: str | None = None,
) -> dict[str, int]:
    """Run ``handler`` over pending events; ack successes, record failures with back-off."""
    published = failed = 0
    for row in pending(session, limit=limit):
        try:
            handler(row)
        except Exception as exc:  # handler errors are data for the retry metadata
            fail(session, row.id, f"{type(exc).__name__}: {exc}")
            failed += 1
        else:
            acknowledge(session, [row.id], consumer=consumer)
            published += 1
    return {"published": published, "failed": failed}
