"""Verification report for /review decisions under the GraphRAG review policy (Issue #80).

The report answers, for one review-state policy, which reviewed relations that policy
would (not) project, with which weight, and which /review batch decided them:

* ``counts``: per ``verification_state``, how many current relations exist and how many
  the policy keeps (``projected_under_policy``);
* ``relations``: a page of relations carrying a /review record (current ``review`` and the
  reverted decisions in ``review_history``) with reviewer, note and ``batch_id``;
* ``batches``: a page of bulk ``batch_id`` s with their per-id outcomes (``applied``,
  ``unchanged``, ``conflict`` ...) from the ``review.batch_decided`` outbox event and
  the relations that still carry that decision.

``projected_under_policy`` describes the policy passed in. The live LightRAG index
(``POST /api/v1/graphrag/project``) projects ``DEFAULT_PROJECTION_REVIEW_STATES`` by default, so
``live_index_applies_policy`` is true exactly when the report's policy is that default.

It is read-only and needs no LightRAG (and does not build the custom KG). An approval is a
review judgement, not a factual verification, so the report never upgrades confidence or
evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sion_api import models
from sqlalchemy import false, func, select
from sqlalchemy.orm import Session, aliased

from .projection import (
    DEFAULT_PROJECTION_REVIEW_STATES,
    _active_at,
    relation_weight,
    resolve_verification_states,
)

# Intended default review policy: approved/machine-verified and pending relations;
# /review-rejected relations only on request (audit/debug). The live engine does not apply it yet.
DEFAULT_REPORT_REVIEW_STATES = ("verified", "unverified")
AUDIT_REPORT_REVIEW_STATES = ("verified", "unverified", "rejected")
REVIEW_BATCH_AGGREGATE = "review_batch"
REVIEW_BATCH_EVENT = "review.batch_decided"
LIVE_INDEX_NOTICE = (
    "projected_under_policy and weight describe the review-state policy in review_states. The live "
    "GraphRAG index (POST /api/v1/graphrag/project) projects verified + unverified relations by "
    "default and excludes rejected ones; ?include_rejected=true is an explicit audit projection."
)
FACT_VERIFICATION_NOTICE = (
    "A /review approval records a reviewer's judgement of a candidate; it does not verify the "
    "underlying fact. Confidence and evidence are left as extracted; human_verified only adds a "
    "bounded ranking boost."
)

_REVIEW_FIELDS = ("decision", "reviewer", "note", "decided_at", "batch_id")
_HISTORY_FIELDS = (*_REVIEW_FIELDS, "reverted_state", "reopened_at", "reopened_by", "reopen_note")


def _pick(record: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    return {field: record.get(field) for field in fields}


def _current_relations_query(at: datetime, columns: tuple[Any, ...]):
    """Relations the projection would consider at ``at``: active, both endpoints present, no self-loop."""
    src = aliased(models.Entity)
    tgt = aliased(models.Entity)
    return (
        select(*columns)
        .join(src, src.id == models.Relation.source_entity_id)
        .join(tgt, tgt.id == models.Relation.target_entity_id)
        .where(_active_at(at), models.Relation.source_entity_id != models.Relation.target_entity_id)
    )


def build_review_report(
    session: Session,
    *,
    review_states: Iterable[str] | None = DEFAULT_REPORT_REVIEW_STATES,
    at: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Return the review verification report for the policy filtered by ``review_states``.

    ``limit``/``offset`` page both ``relations`` and ``batches`` independently;
    ``batch_id`` restricts both to one bulk decision.
    """
    if limit < 1 or offset < 0:
        raise ValueError("limit must be >= 1 and offset >= 0")
    states = None if review_states is None else tuple(review_states)
    allowed = resolve_verification_states(states)
    effective_at = at or datetime.now(timezone.utc)
    if effective_at.tzinfo is None:
        effective_at = effective_at.replace(tzinfo=timezone.utc)

    def kept(state: str) -> bool:
        return allowed is None or state in allowed

    counts: dict[str, dict[str, int]] = {}
    for state, total in session.execute(
        _current_relations_query(effective_at, (models.Relation.verification_state, func.count()))
        .group_by(models.Relation.verification_state)
    ):
        counts[state] = {"total": int(total), "projected_under_policy": int(total) if kept(state) else 0}

    relations: list[dict[str, Any]] = []
    relations_total = 0
    batch_relations: dict[str, list[str]] = {}
    rows = session.execute(
        _current_relations_query(
            effective_at,
            (
                models.Relation.stable_key,
                models.Relation.verification_state,
                models.Relation.confidence,
                models.Relation.properties,
            ),
        ).order_by(models.Relation.stable_key)
    )
    for stable_key, state, confidence, properties in rows:
        properties = properties or {}
        review = _pick(properties.get("review"), _REVIEW_FIELDS)
        history = [h for h in (_pick(item, _HISTORY_FIELDS) for item in properties.get("review_history") or []) if h]
        if review is None and not history:
            continue
        if review and review.get("batch_id"):
            batch_relations.setdefault(str(review["batch_id"]), []).append(stable_key)
        if batch_id is not None and str((review or {}).get("batch_id")) != batch_id:
            continue
        relations_total += 1
        if relations_total <= offset or len(relations) >= limit:
            continue
        projected = kept(state)
        relations.append({
            "stable_key": stable_key,
            "verification_state": state,
            "confidence": confidence,
            "projected_under_policy": projected,
            "weight": relation_weight(confidence, state, properties) if projected else None,
            "review": review,
            "review_history": history,
        })

    # Batch ids in log order (only ids are loaded), then batches decided before the batch log
    # existed (they are known only from the relations that still carry their batch_id).
    batch_query = select(models.OutboxEvent.id, models.OutboxEvent.aggregate_id).where(
        models.OutboxEvent.aggregate_type == REVIEW_BATCH_AGGREGATE,
        models.OutboxEvent.event_type == REVIEW_BATCH_EVENT,
    )
    if batch_id is not None:
        try:
            batch_query = batch_query.where(models.OutboxEvent.aggregate_id == uuid.UUID(batch_id))
        except ValueError:
            batch_query = batch_query.where(false())
    ordered: list[tuple[str, Any]] = [
        (str(aggregate_id), event_id)
        for event_id, aggregate_id in session.execute(
            batch_query.order_by(models.OutboxEvent.created_at, models.OutboxEvent.id)
        )
    ]
    logged = {key for key, _ in ordered}
    legacy = sorted(set(batch_relations) - logged)
    if batch_id is not None:
        legacy = [key for key in legacy if key == batch_id]
    ordered.extend((key, None) for key in legacy)
    page = ordered[offset : offset + limit]
    event_ids = [event_id for _, event_id in page if event_id is not None]
    events = (
        {event.id: event for event in session.scalars(select(models.OutboxEvent).where(models.OutboxEvent.id.in_(event_ids)))}
        if event_ids
        else {}
    )
    batches: list[dict[str, Any]] = []
    for key, event_id in page:
        payload = (events[event_id].payload or {}) if event_id is not None else {}
        batches.append({
            "batch_id": key,
            "decision": payload.get("decision"),
            "reviewer": payload.get("reviewer"),
            "note": payload.get("note"),
            "decided_at": payload.get("decided_at"),
            "counts": payload.get("counts"),
            "results": payload.get("results", []),
            "current_relations": sorted(batch_relations.get(key, [])),
        })

    return {
        "canonical": False,
        "review_states": None if states is None else list(states),
        "projected_states": None if allowed is None else sorted(allowed),
        "live_index_applies_policy": allowed == resolve_verification_states(DEFAULT_PROJECTION_REVIEW_STATES),
        "policy_notice": LIVE_INDEX_NOTICE,
        "fact_verification": False,
        "notice": FACT_VERIFICATION_NOTICE,
        "counts": dict(sorted(counts.items())),
        "limit": limit,
        "offset": offset,
        "batch_id": batch_id,
        "relations_total": relations_total,
        "relations": relations,
        "batches_total": len(ordered),
        "batches": batches,
    }

