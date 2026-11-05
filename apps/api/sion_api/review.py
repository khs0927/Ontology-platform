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

``reopen`` is the supported way to undo a mistaken decision or to re-review a candidate: it
moves an approved/rejected candidate back to pending, with a required note, and keeps the
reverted decision (reviewer, note, batch_id) in ``properties.review_history`` (nothing is
deleted). The opposite decision is never applied directly over an existing one: approve after
reject (or reject after approve) is a 409 / ``conflict`` until the candidate is reopened.

An approval records a person's review judgement of a candidate. It is not a factual
verification of the source: the relation's confidence and evidence are left as extracted, and
GraphRAG only adds a bounded ranking boost for ``human_verified``.

Every bulk call that applies at least one decision also writes a ``review.batch_decided`` outbox
event (aggregate ``review_batch``, id = ``batch_id``) with the per-id results, in the same
transaction, so projection consumers and the review report can trace each batch.

Safe review writes (#71 steps E/F):

* **Version** - ``properties.review_rev`` (exposed as ``version``) is bumped by every transition.
  Writers may send ``expected_version``; a mismatch is a ``VersionConflict`` (HTTP 409 with the
  current version) and the conditional UPDATE pins the same value, so the check is a true
  compare-and-swap. Omitting it keeps the old behaviour unless strict mode
  (``SION_REVIEW_REQUIRE_VERSION``) is on.
* **Dry run** - the exact same code path runs inside the transaction and is rolled back, so the
  response is precisely what a real call would have returned, but nothing is written.
* **Decision log** - every applied transition appends one entry to ``properties.review_log``
  (action, reviewer, note, batch_id, prior/new state, from/to version, timestamp). ``replay_log``
  folds the log from the initial pending state and must reproduce the stored state and version.
* **Low-trust edges** - inferred candidates backed only by co-occurrence (or explicitly marked
  ``trust: low`` / ``low_trust: true``) cannot be approved without ``confirm_low_trust``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import models

log = logging.getLogger(__name__)

STATUS_TO_STATE = {"pending": "unverified", "approved": "human_verified", "rejected": "rejected"}
STATE_TO_STATUS = {v: k for k, v in STATUS_TO_STATE.items()}
CANDIDATE_SOURCE_KINDS = ("inferred", "imported")


class ReviewError(Exception):
    pass


class NotACandidate(ReviewError):
    pass


class AlreadyReviewed(ReviewError):
    pass


class VersionConflict(ReviewError):
    """``expected_version`` does not match the stored review version (HTTP 409)."""

    def __init__(self, message: str, *, expected_version: int | None, current_version: int, status: str | None):
        super().__init__(message)
        self.expected_version = expected_version
        self.current_version = current_version
        self.status = status

    def as_detail(self) -> dict[str, Any]:
        return {
            "error": "version_conflict",
            "message": str(self),
            "expected_version": self.expected_version,
            "current_version": self.current_version,
            "status": self.status,
        }


class VersionRequired(ReviewError):
    """Strict mode: a review write without ``expected_version`` (HTTP 428)."""

    def __init__(self, message: str, *, ids: list[str] | None = None):
        super().__init__(message)
        self.ids = ids or []

    def as_detail(self) -> dict[str, Any]:
        return {"error": "version_required", "message": str(self), "ids": self.ids}


class LowTrustConfirmationRequired(ReviewError):
    """Approving a low-trust inferred edge needs ``confirm_low_trust: true`` (HTTP 422)."""

    def __init__(self, message: str, *, ids: list[str]):
        super().__init__(message)
        self.ids = ids

    def as_detail(self) -> dict[str, Any]:
        return {"error": "low_trust_confirmation_required", "message": str(self), "ids": self.ids}


LOW_TRUST_RULES = frozenset({"co-occurrence", "cooccurrence"})


def is_low_trust(row: models.Relation) -> bool:
    """Weakest machine guesses: explicit low-trust marks, or inferred edges backed only by co-occurrence."""
    properties = row.properties or {}
    if properties.get("low_trust") is True or str(properties.get("trust") or "").lower() == "low":
        return True
    rules = properties.get("rules") or ([properties["rule"]] if properties.get("rule") else [])
    return row.source_kind == "inferred" and bool(rules) and all(str(r).lower() in LOW_TRUST_RULES for r in rules)


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


def _source_checksum(properties: dict[str, Any]) -> str | None:
    """sha256 of the source file the candidate (or one evidence row) was read from, when recorded."""
    for key in ("provenance", "su_evidence"):
        value = properties.get(key)
        if isinstance(value, dict):
            for field in ("source_sha256", "sha256"):
                if value.get(field):
                    return str(value[field])
    for field in ("source_sha256", "sha256"):
        if properties.get(field):
            return str(properties[field])
    return None


def _source_locator(properties: dict[str, Any]) -> str | None:
    for key in ("provenance", "su_evidence"):
        value = properties.get(key)
        if isinstance(value, dict) and value.get("locator"):
            return str(value["locator"])
    return None


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
        "source_locator": _source_locator(properties),
        "source_sha256": _source_checksum(properties),
        "review": properties.get("review"),
        "version": _review_rev(properties),
        "low_trust": is_low_trust(row),
        "evidence_count": evidence_count,
        "evidence": [
            {
                "id": str(e.id),
                "source_uri": e.source_uri,
                "source_locator": e.source_locator,
                "excerpt": (e.properties or {}).get("excerpt"),
                "excerpt_hash": e.excerpt_hash,
                "source_sha256": _source_checksum(e.properties or {}),
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
    session: Session,
    row: models.Relation,
    *,
    expected_state: str,
    new_state: str,
    properties: dict[str, Any],
    log_entry: dict[str, Any],
) -> bool:
    """Atomically move ``row`` from ``expected_state`` to ``new_state``; True only if this call did it.

    The predicate also pins ``properties.review_rev`` as it was when ``row`` was read, and every
    transition bumps it, so an A->B->A cycle by another reviewer (decide then reopen) in between
    cannot let a stale request pass and overwrite the newer history. ``log_entry`` is appended to
    ``properties.review_log`` in the same UPDATE, so a decision and its audit record are one write.
    """
    rev = _review_rev(row.properties)
    entry = {**log_entry, "prior_state": expected_state, "new_state": new_state, "from_version": rev, "to_version": rev + 1}
    properties = {
        **properties,
        "review_rev": rev + 1,
        "review_log": [*((row.properties or {}).get("review_log") or []), entry],
    }
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


def _current_version(session: Session, relation_id: uuid.UUID) -> int:
    """Fresh committed review version from the database (bypasses the session's identity map)."""
    value = session.execute(
        select(func.coalesce(models.Relation.properties["review_rev"].as_integer(), 0)).where(
            models.Relation.id == relation_id
        )
    ).scalar_one_or_none()
    return int(value or 0)


def _check_version(row: models.Relation, expected_version: int | None, *, require_version: bool) -> None:
    if expected_version is None:
        if require_version:
            raise VersionRequired("expected_version is required for review writes", ids=[str(row.id)])
        return
    current = _review_rev(row.properties)
    if expected_version != current:
        status = STATE_TO_STATUS.get(row.verification_state, row.verification_state)
        raise VersionConflict(
            f"candidate version is {current}, not {expected_version}; reload and decide again",
            expected_version=expected_version,
            current_version=current,
            status=status,
        )


def _apply_decision(
    session: Session,
    row: models.Relation,
    *,
    approve: bool,
    reviewer: str | None,
    note: str | None,
    batch_id: str | None = None,
    confirmed_low_trust: bool = False,
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
    if confirmed_low_trust:
        properties["review"]["confirmed_low_trust"] = True
    log_entry = {
        "action": properties["review"]["decision"],
        "reviewer": properties["review"]["reviewer"],
        "note": note,
        "batch_id": batch_id,
        "at": decided_at,
        **({"confirmed_low_trust": True} if confirmed_low_trust else {}),
    }
    if not _compare_and_set(
        session, row, expected_state="unverified", new_state=state, properties=properties, log_entry=log_entry
    ):
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


def _lost_race(session: Session, relation_id: uuid.UUID, expected_version: int | None, message: str) -> ReviewError:
    """Error for a conditional UPDATE that matched no row (call after rolling back)."""
    if expected_version is not None:
        now = _current_state(session, relation_id)
        return VersionConflict(
            "candidate changed concurrently; reload and decide again",
            expected_version=expected_version,
            current_version=_current_version(session, relation_id),
            status=STATE_TO_STATUS.get(now, now),
        )
    return AlreadyReviewed(message)


def decide(
    session: Session,
    relation_id: uuid.UUID,
    *,
    approve: bool,
    reviewer: str | None = None,
    note: str | None = None,
    expected_version: int | None = None,
    confirm_low_trust: bool = False,
    dry_run: bool = False,
    require_version: bool = False,
) -> dict[str, Any]:
    """Decide one pending candidate; returns its serialized (would-be, for ``dry_run``) state.

    ``dry_run`` runs exactly the same checks and conditional UPDATE, serializes the result and then
    rolls the transaction back, so the answer is what a real call would return and nothing is stored.
    """
    row = get_candidate(session, relation_id)
    _check_version(row, expected_version, require_version=require_version)
    if row.verification_state != "unverified":
        raise AlreadyReviewed(_already(row.verification_state))
    low_trust = approve and is_low_trust(row)
    if low_trust and not confirm_low_trust:
        raise LowTrustConfirmationRequired(
            "low-trust inferred edge: approving it needs confirm_low_trust=true (explicit human confirmation)",
            ids=[str(row.id)],
        )
    if not _apply_decision(session, row, approve=approve, reviewer=reviewer, note=note, confirmed_low_trust=low_trust):
        session.rollback()
        raise _lost_race(session, relation_id, expected_version, _already(_current_state(session, relation_id)))
    return _finish(session, row, dry_run=dry_run)


def _finish(session: Session, row: models.Relation, *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        session.flush()
        body = serialize(session, row)
        session.rollback()
        return {**body, "dry_run": True}
    session.commit()
    session.refresh(row)
    return serialize(session, row)


class NotReviewed(ReviewError):
    pass


def reopen(
    session: Session,
    relation_id: uuid.UUID,
    *,
    note: str,
    reviewer: str | None = None,
    expected_version: int | None = None,
    dry_run: bool = False,
    require_version: bool = False,
) -> dict[str, Any]:
    """Undo a decision: approved/rejected -> pending, atomically, keeping the reverted decision on record."""
    if not (note or "").strip():
        raise ReviewError("note is required to reopen a decision")
    row = get_candidate(session, relation_id)
    _check_version(row, expected_version, require_version=require_version)
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
    log_entry = {
        "action": "reopened",
        "reviewer": reviewer or "anonymous",
        "note": note.strip(),
        "batch_id": None,
        "at": reopened_at,
    }
    if not _compare_and_set(
        session, row, expected_state=expected, new_state="unverified", properties=properties, log_entry=log_entry
    ):
        session.rollback()
        now = _current_state(session, relation_id)
        raise _lost_race(
            session, relation_id, expected_version,
            f"candidate changed concurrently (now {STATE_TO_STATUS.get(now, now)}); reload and retry",
        )
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
    return _finish(session, row, dry_run=dry_run)


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
    expected_version: int | None = None,
    confirm_low_trust: bool = False,
) -> dict[str, Any]:
    rid = str(relation_id)
    row = session.get(models.Relation, relation_id)
    if row is None:
        return {"id": rid, "result": "not_found", "detail": "relation not found"}
    if not _is_candidate(row):
        return {"id": rid, "result": "not_candidate", "detail": "relation is not a candidate"}
    status = STATE_TO_STATUS.get(row.verification_state, row.verification_state)
    version = _review_rev(row.properties)
    if row.verification_state == target_state:
        return {"id": rid, "result": "unchanged", "status": status, "version": version, "detail": f"already {status}"}
    if expected_version is not None and expected_version != version:
        return {
            "id": rid, "result": "conflict", "status": status, "version": version,
            "detail": f"version conflict: candidate is at version {version}, not {expected_version}; reload and decide again",
        }
    if row.verification_state != "unverified":
        return {"id": rid, "result": "conflict", "status": status, "version": version, "detail": f"candidate already {status}"}
    if not _apply_decision(
        session, row, approve=approve, reviewer=reviewer, note=note, batch_id=batch_id,
        confirmed_low_trust=approve and confirm_low_trust and is_low_trust(row),
    ):
        # Lost a race: someone changed it between our read and our conditional update.
        now = _current_state(session, relation_id)
        status = STATE_TO_STATUS.get(now, now)
        result = "unchanged" if now == target_state else "conflict"
        return {
            "id": rid, "result": result, "status": status,
            "version": _current_version(session, relation_id), "detail": _already(now),
        }
    return {"id": rid, "result": "applied", "status": decision, "version": version + 1}


BULK_RESULTS = ("applied", "unchanged", "conflict", "not_found", "not_candidate", "invalid_id")
# Results that leave the candidate in the requested state (``unchanged`` = idempotent repeat).
BULK_OK = frozenset({"applied", "unchanged"})
REVIEW_BATCH_AGGREGATE = "review_batch"
REVIEW_BATCH_EVENT = "review.batch_decided"


def decide_bulk(
    session: Session,
    ids: list[str],
    *,
    approve: bool,
    note: str,
    reviewer: str | None = None,
    expected_versions: dict[str, int] | None = None,
    confirm_low_trust: bool = False,
    dry_run: bool = False,
    require_version: bool = False,
) -> dict[str, Any]:
    """Apply one decision to each listed candidate; per-id results, idempotent, one commit.

    ``expected_versions`` maps id -> the version the reviewer saw; a mismatch is a per-item
    ``conflict`` (with the current ``version``). ``dry_run`` returns the exact per-item results of
    a real call and rolls everything back (``batch_id`` stays null: nothing was recorded).
    Approving a low-trust candidate without ``confirm_low_trust`` refuses the whole request.

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
    versions = {str(k).strip(): v for k, v in (expected_versions or {}).items()}
    if require_version:
        missing = [key for key in valid.values() if key not in versions]
        if missing:
            raise VersionRequired("expected_versions must list every id in strict mode", ids=missing)
    if approve and not confirm_low_trust:
        low = [
            key
            for relation_id, key in valid.items()
            if (row := session.get(models.Relation, relation_id)) is not None
            and _is_candidate(row)
            and row.verification_state == "unverified"
            and is_low_trust(row)
        ]
        if low:
            session.rollback()
            raise LowTrustConfirmationRequired(
                "low-trust inferred edges selected: approving them needs confirm_low_trust=true", ids=low
            )
    # Take row locks in one global order (sorted ids): every successful conditional UPDATE keeps its
    # lock until the single commit, so two bulk requests listing the same candidates in opposite
    # orders would otherwise deadlock on PostgreSQL. The response keeps the caller's order.
    for relation_id in sorted(valid):
        by_key[valid[relation_id]] = _bulk_one(
            session, relation_id, approve=approve, target_state=target_state, decision=decision,
            reviewer=reviewer, note=note, batch_id=batch_id,
            expected_version=versions.get(valid[relation_id]), confirm_low_trust=confirm_low_trust,
        )
    results = [by_key[key] for key in order]
    applied = sum(1 for r in results if r["result"] == "applied")
    recorded = bool(applied) and not dry_run
    for r in results:
        # Per-item report (#80 step 4): explicit success flag + reason, and the batch id that
        # recorded the decision (only for items this call actually wrote).
        r["ok"] = r["result"] in BULK_OK
        r["reason"] = None if r["result"] == "applied" else r.get("detail")
        r["batch_id"] = batch_id if recorded and r["result"] == "applied" else None
    counts = {name: sum(1 for r in results if r["result"] == name) for name in BULK_RESULTS}
    succeeded = sum(1 for r in results if r["ok"])
    if recorded:
        # Batch log (#80): the per-id outcomes commit atomically with the decisions they describe.
        session.add(
            models.OutboxEvent(
                id=uuid.uuid4(),
                aggregate_type=REVIEW_BATCH_AGGREGATE,
                aggregate_id=uuid.UUID(batch_id),
                event_type=REVIEW_BATCH_EVENT,
                payload={
                    "batch_id": batch_id,
                    "decision": decision,
                    "reviewer": reviewer or "anonymous",
                    "note": note,
                    "decided_at": datetime.now(timezone.utc).isoformat(),
                    "requested": len(results),
                    "counts": counts,
                    "results": [
                        {"id": r["id"], "result": r["result"], "ok": r["ok"], "reason": r["reason"]} for r in results
                    ],
                },
                attempts=0,
            )
        )
        session.commit()
        log.info(
            "review batch %s: %s %d applied of %d requested (%s)",
            batch_id, decision, applied, len(results),
            ", ".join(f"{name}={n}" for name, n in counts.items() if n),
        )
    else:
        session.rollback()
    return {
        "decision": decision,
        "dry_run": dry_run,
        "batch_id": batch_id if recorded else None,
        "requested": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "counts": counts,
        "results": results,
    }


def replay_log(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold a decision log from the initial pending state; reports the first inconsistency.

    Each entry must start from the state/version the previous one ended in, so a valid log replays
    to exactly one final (state, version) pair.
    """
    state, version, errors = "unverified", 0, []
    for index, entry in enumerate(entries):
        if entry.get("prior_state") != state or entry.get("from_version") != version:
            errors.append(
                f"entry {index}: expected prior_state={state}/from_version={version}, "
                f"got {entry.get('prior_state')}/{entry.get('from_version')}"
            )
            break
        state, version = entry.get("new_state"), entry.get("to_version")
    return {"state": state, "status": STATE_TO_STATUS.get(state, state), "version": version, "errors": errors}


def audit(session: Session, relation_id: uuid.UUID) -> dict[str, Any]:
    """Decision log of one candidate plus a replay check against the stored state."""
    row = get_candidate(session, relation_id)
    properties = row.properties or {}
    entries = list(properties.get("review_log") or [])
    replayed = replay_log(entries)
    current = {
        "state": row.verification_state,
        "status": STATE_TO_STATUS.get(row.verification_state, row.verification_state),
        "version": _review_rev(properties),
    }
    return {
        "id": str(row.id),
        "current": current,
        "log": entries,
        "replay": replayed,
        # False for candidates decided before the log existed (their version predates the log).
        "consistent": not replayed["errors"]
        and replayed["state"] == current["state"]
        and replayed["version"] == current["version"],
    }
