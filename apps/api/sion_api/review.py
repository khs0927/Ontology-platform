"""Review queue for candidate relations.

A candidate is a ``relations`` row with ``properties.candidate = True`` (written
by ``sion_ingestion.relation_extraction`` or by a graph-export import). Its
``verification_state`` is the review status:

* ``unverified``      -> pending
* ``human_verified``  -> approved (promoted to a verified relation)
* ``rejected``        -> rejected (kept for provenance, never deleted)

Decisions are recorded in ``properties.review`` and copied onto the candidate's
evidence rows; the original extractor, rules and evidence are left untouched.

``decide_bulk`` applies one human decision to many explicitly listed ids. Each
candidate gets exactly the same per-item audit record (plus a shared
``batch_id``); nothing is ever approved without an id the reviewer selected.

Every state change is a compare-and-set: ``UPDATE relations ... WHERE id = :id AND
verification_state = :expected``. The affected-row count decides whether the decision was
applied, so two reviewers deciding the same pending candidate concurrently can never both
"win" (PostgreSQL re-checks the predicate after the row lock is released; SQLite serializes
writers). The loser gets ``AlreadyReviewed`` (per item) or ``conflict``/``unchanged`` (bulk).

``reopen`` is the supported way to undo a mistaken decision: it moves an approved/rejected
candidate back to pending, with a required note, and keeps the reverted decision in
``properties.review_history`` (nothing is deleted).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
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


def _source_file(properties: dict[str, Any], evidence: list[models.Evidence]) -> str | None:
    for key in ("provenance", "su_evidence"):
        value = properties.get(key)
        if isinstance(value, dict) and value.get("source_file"):
            return str(value["source_file"])
    for e in evidence:
        if e.source_uri:
            return e.source_uri.rstrip("/").rsplit("/", 1)[-1]
    return None


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
        "source_file": _source_file(properties, evidence),
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


def _review_rev(properties: dict[str, Any] | None) -> int:
    value = (properties or {}).get("review_rev")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _compare_and_set(
    session: Session, row: models.Relation, *, expected_state: str, new_state: str, properties: dict[str, Any]
) -> bool:
    """Atomically move ``row`` from ``expected_state`` to ``new_state``; True only if this call did it.

    The predicate also pins ``properties.review_rev`` as it was when ``row`` was read, and every
    transition bumps it, so an A->B->A cycle by another reviewer (decide then reopen) in between
    cannot let a stale request pass and overwrite the newer history.
    """
    rev = _review_rev(row.properties)
    properties = {**properties, "review_rev": rev + 1}
    result = session.execute(
        update(models.Relation)
        .where(models.Relation.id == row.id)
        .where(models.Relation.verification_state == expected_state)
        .where(func.coalesce(models.Relation.properties["review_rev"].as_integer(), 0) == rev)
        .values(verification_state=new_state, properties=properties)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    # Mirror the committed-to-be values onto the ORM row: the flush then rewrites the same values
    # (we already hold the row's write lock) and the outbox before_flush hook emits relation.updated
    # exactly as it did for the previous ORM-only path.
    row.verification_state = new_state
    row.properties = properties
    return True


def _current_state(session: Session, relation_id: uuid.UUID) -> str | None:
    """Fresh committed state from the database (bypasses the session's identity map)."""
    return session.execute(
        select(models.Relation.verification_state).where(models.Relation.id == relation_id)
    ).scalar_one_or_none()


def _apply_decision(
    session: Session,
    row: models.Relation,
    *,
    approve: bool,
    reviewer: str | None,
    note: str | None,
    batch_id: str | None = None,
) -> bool:
    """Record one decision on ``row`` and its evidence rows (no commit).

    Returns False (and writes nothing) when the candidate is no longer pending in the database,
    e.g. because a concurrent reviewer decided it first.
    """
    state = "human_verified" if approve else "rejected"
    decided_at = datetime.now(timezone.utc).isoformat()
    properties = dict(row.properties or {})
    properties["review"] = {
        "decision": "approved" if approve else "rejected",
        "reviewer": reviewer or "anonymous",
        "note": note,
        "decided_at": decided_at,
        "previous_state": "unverified",
        "previous_confidence": row.confidence,
    }
    if batch_id is not None:
        properties["review"]["batch_id"] = batch_id
    if not _compare_and_set(session, row, expected_state="unverified", new_state=state, properties=properties):
        return False
    for evidence in session.scalars(select(models.Evidence).where(models.Evidence.relation_id == row.id)):
        evidence.verification_state = state
        evidence_props = dict(evidence.properties or {})
        evidence_props["review"] = {"decision": properties["review"]["decision"], "decided_at": decided_at}
        if batch_id is not None:
            evidence_props["review"]["batch_id"] = batch_id
        evidence.properties = evidence_props
    return True


def _already(state: str | None) -> str:
    if state == "unverified":  # decided and reopened by someone else since this request read it
        return "candidate changed concurrently (pending again); reload and decide again"
    return f"candidate already {STATE_TO_STATUS.get(state, state)}"


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
        raise AlreadyReviewed(_already(row.verification_state))
    if not _apply_decision(session, row, approve=approve, reviewer=reviewer, note=note):
        session.rollback()
        raise AlreadyReviewed(_already(_current_state(session, relation_id)))
    session.commit()
    session.refresh(row)
    return row


class NotReviewed(ReviewError):
    pass


def reopen(session: Session, relation_id: uuid.UUID, *, note: str, reviewer: str | None = None) -> models.Relation:
    """Undo a decision: approved/rejected -> pending, atomically, keeping the reverted decision on record."""
    if not (note or "").strip():
        raise ReviewError("note is required to reopen a decision")
    row = get_candidate(session, relation_id)
    expected = row.verification_state
    if expected == "unverified":
        raise NotReviewed("candidate is already pending")
    if expected not in ("human_verified", "rejected"):
        # e.g. machine_verified: not a /review decision, so there is nothing to reopen.
        raise NotReviewed(f"only approved/rejected review decisions can be reopened (state is {expected})")
    reopened_at = datetime.now(timezone.utc).isoformat()
    properties = dict(row.properties or {})
    reverted = dict(properties.pop("review", None) or {})
    reverted.update(
        {
            "reverted_state": expected,
            "reopened_at": reopened_at,
            "reopened_by": reviewer or "anonymous",
            "reopen_note": note.strip(),
        }
    )
    properties["review_history"] = [*(properties.get("review_history") or []), reverted]
    if not _compare_and_set(session, row, expected_state=expected, new_state="unverified", properties=properties):
        session.rollback()
        now = _current_state(session, relation_id)
        raise AlreadyReviewed(f"candidate changed concurrently (now {STATE_TO_STATUS.get(now, now)}); reload and retry")
    for evidence in session.scalars(select(models.Evidence).where(models.Evidence.relation_id == row.id)):
        evidence.verification_state = "unverified"
        evidence_props = dict(evidence.properties or {})
        previous = evidence_props.pop("review", None)
        if previous is not None:
            evidence_props["review_history"] = [
                *(evidence_props.get("review_history") or []),
                {**previous, "reopened_at": reopened_at},
            ]
        evidence.properties = evidence_props
    session.commit()
    session.refresh(row)
    return row


def _bulk_one(
    session: Session,
    relation_id: uuid.UUID,
    *,
    approve: bool,
    target_state: str,
    decision: str,
    reviewer: str | None,
    note: str,
    batch_id: str,
) -> dict[str, Any]:
    rid = str(relation_id)
    row = session.get(models.Relation, relation_id)
    if row is None:
        return {"id": rid, "result": "not_found", "detail": "relation not found"}
    if not _is_candidate(row):
        return {"id": rid, "result": "not_candidate", "detail": "relation is not a candidate"}
    status = STATE_TO_STATUS.get(row.verification_state, row.verification_state)
    if row.verification_state == target_state:
        return {"id": rid, "result": "unchanged", "status": status, "detail": f"already {status}"}
    if row.verification_state != "unverified":
        return {"id": rid, "result": "conflict", "status": status, "detail": f"candidate already {status}"}
    if not _apply_decision(session, row, approve=approve, reviewer=reviewer, note=note, batch_id=batch_id):
        # Lost a race: someone changed it between our read and our conditional update.
        now = _current_state(session, relation_id)
        status = STATE_TO_STATUS.get(now, now)
        result = "unchanged" if now == target_state else "conflict"
        return {"id": rid, "result": result, "status": status, "detail": _already(now)}
    return {"id": rid, "result": "applied", "status": decision}


BULK_RESULTS = ("applied", "unchanged", "conflict", "not_found", "not_candidate", "invalid_id")


def decide_bulk(
    session: Session,
    ids: list[str],
    *,
    approve: bool,
    note: str,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Apply one decision to each listed candidate; per-id results, idempotent, one commit.

    * ``applied``       pending -> decided now (same audit record as the per-item route)
    * ``unchanged``     already has this decision (repeat call; nothing rewritten)
    * ``conflict``      already has the opposite decision (left as is)
    * ``not_found`` / ``not_candidate`` / ``invalid_id``  skipped
    """
    decision = "approved" if approve else "rejected"
    target_state = STATUS_TO_STATE[decision]
    batch_id = str(uuid.uuid4())
    order: list[str] = []
    seen: set[str] = set()
    by_key: dict[str, dict[str, Any]] = {}
    valid: dict[uuid.UUID, str] = {}
    for raw in ids:
        key = str(raw).strip()
        if key in seen:
            continue
        seen.add(key)
        order.append(key)
        try:
            valid[uuid.UUID(key)] = key
        except ValueError:
            by_key[key] = {"id": key, "result": "invalid_id", "detail": "not a UUID"}
    # Take row locks in one global order (sorted ids): every successful conditional UPDATE keeps its
    # lock until the single commit, so two bulk requests listing the same candidates in opposite
    # orders would otherwise deadlock on PostgreSQL. The response keeps the caller's order.
    for relation_id in sorted(valid):
        by_key[valid[relation_id]] = _bulk_one(
            session, relation_id, approve=approve, target_state=target_state, decision=decision,
            reviewer=reviewer, note=note, batch_id=batch_id,
        )
    results = [by_key[key] for key in order]
    applied = sum(1 for r in results if r["result"] == "applied")
    if applied:
        session.commit()
    else:
        session.rollback()
    counts = {name: sum(1 for r in results if r["result"] == name) for name in BULK_RESULTS}
    return {
        "decision": decision,
        "batch_id": batch_id if applied else None,
        "requested": len(results),
        "counts": counts,
        "results": results,
    }
