"""Review queue for candidate relations.

A candidate is a ``relations`` row with ``properties.candidate = True`` (written
by ``sion_ingestion.relation_extraction`` or by a graph-export import). Its
``verification_state`` is the review status:

* ``unverified``      -> pending
* ``human_verified``  -> approved (promoted to a verified relation)
* ``rejected``        -> rejected (kept for provenance, never deleted)

Decisions are recorded in ``properties.review`` and copied onto the candidate's
evidence rows; the original extractor, rules and evidence are left untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models

STATUS_TO_STATE = {"pending": "unverified", "approved": "human_verified", "rejected": "rejected"}
STATE_TO_STATUS = {v: k for k, v in STATUS_TO_STATE.items()}
CANDIDATE_SOURCE_KINDS = ("inferred", "imported")


class ReviewError(Exception):
    pass


class NotACandidate(ReviewError):
    pass


class AlreadyReviewed(ReviewError):
    pass


def _is_candidate(row: models.Relation) -> bool:
    return bool((row.properties or {}).get("candidate"))


def _candidate_rows(session: Session, states: list[str]) -> list[models.Relation]:
    statement = (
        select(models.Relation)
        .where(models.Relation.verification_state.in_(states))
        .where(models.Relation.source_kind.in_(CANDIDATE_SOURCE_KINDS))
        .order_by(models.Relation.confidence.desc(), models.Relation.created_at, models.Relation.id)
    )
    return [row for row in session.scalars(statement) if _is_candidate(row)]


def _entity_brief(row: models.Entity | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"id": str(row.id), "stable_key": row.stable_key, "name": row.name, "entity_type_id": row.entity_type_id, "category": row.category}


def serialize(session: Session, row: models.Relation, *, evidence_limit: int = 10) -> dict[str, Any]:
    evidence = list(
        session.scalars(
            select(models.Evidence)
            .where(models.Evidence.relation_id == row.id)
            .order_by(models.Evidence.created_at, models.Evidence.id)
            .limit(evidence_limit)
        )
    )
    evidence_count = session.scalar(select(func.count()).select_from(models.Evidence).where(models.Evidence.relation_id == row.id))
    properties = dict(row.properties or {})
    return {
        "id": str(row.id),
        "stable_key": row.stable_key,
        "status": STATE_TO_STATUS.get(row.verification_state, row.verification_state),
        "verification_state": row.verification_state,
        "relation_type_id": row.relation_type_id,
        "confidence": row.confidence,
        "source_kind": row.source_kind,
        "source": _entity_brief(session.get(models.Entity, row.source_entity_id)),
        "target": _entity_brief(session.get(models.Entity, row.target_entity_id)),
        "extractor": properties.get("extractor"),
        "rules": properties.get("rules") or ([properties["rule"]] if properties.get("rule") else []),
        "support": properties.get("support", evidence_count),
        "provenance": properties.get("provenance"),
        "review": properties.get("review"),
        "evidence_count": evidence_count,
        "evidence": [
            {
                "id": str(e.id),
                "source_uri": e.source_uri,
                "source_locator": e.source_locator,
                "excerpt": (e.properties or {}).get("excerpt"),
                "excerpt_hash": e.excerpt_hash,
                "extractor": e.extractor,
                "model": e.model,
                "confidence": e.confidence,
                "verification_state": e.verification_state,
            }
            for e in evidence
        ],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_candidates(session: Session, *, status: str = "pending", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    if status == "all":
        states = list(STATUS_TO_STATE.values())
    elif status in STATUS_TO_STATE:
        states = [STATUS_TO_STATE[status]]
    else:
        raise ReviewError(f"status must be one of pending, approved, rejected, all (got {status!r})")
    rows = _candidate_rows(session, states)
    counts = {name: 0 for name in STATUS_TO_STATE}
    for row in _candidate_rows(session, list(STATUS_TO_STATE.values())):
        counts[STATE_TO_STATUS[row.verification_state]] += 1
    page = rows[offset : offset + limit]
    return {
        "status": status,
        "total": len(rows),
        "counts": counts,
        "limit": limit,
        "offset": offset,
        "candidates": [serialize(session, row) for row in page],
    }


def get_candidate(session: Session, relation_id: uuid.UUID) -> models.Relation:
    row = session.get(models.Relation, relation_id)
    if row is None:
        raise LookupError("relation not found")
    if not _is_candidate(row):
        raise NotACandidate("relation is not a candidate")
    return row


def decide(
    session: Session,
    relation_id: uuid.UUID,
    *,
    approve: bool,
    reviewer: str | None = None,
    note: str | None = None,
) -> models.Relation:
    row = get_candidate(session, relation_id)
    if row.verification_state != "unverified":
        raise AlreadyReviewed(f"candidate already {STATE_TO_STATUS.get(row.verification_state, row.verification_state)}")
    state = "human_verified" if approve else "rejected"
    decided_at = datetime.now(timezone.utc).isoformat()
    properties = dict(row.properties or {})
    properties["review"] = {
        "decision": "approved" if approve else "rejected",
        "reviewer": reviewer or "anonymous",
        "note": note,
        "decided_at": decided_at,
        "previous_state": row.verification_state,
        "previous_confidence": row.confidence,
    }
    row.properties = properties
    row.verification_state = state
    for evidence in session.scalars(select(models.Evidence).where(models.Evidence.relation_id == row.id)):
        evidence.verification_state = state
        evidence_props = dict(evidence.properties or {})
        evidence_props["review"] = {"decision": properties["review"]["decision"], "decided_at": decided_at}
        evidence.properties = evidence_props
    session.commit()
    session.refresh(row)
    return row
