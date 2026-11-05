"""Verification report for /review decisions in the GraphRAG projection (Issue #80).

The report answers, for one projection policy, which reviewed relations are (not)
projected, with which weight, and which /review batch decided them:

* ``counts``: per ``verification_state``, how many current relations exist and how many
  the projection keeps;
* ``relations``: every relation carrying a /review record (current ``review`` and the
  reverted decisions in ``review_history``) with reviewer, note and ``batch_id``;
* ``batches``: each bulk ``batch_id`` with its per-id outcomes (``applied``,
  ``unchanged``, ``conflict`` ...) from the ``review.batch_decided`` outbox event and
  the relations that still carry that decision.

It is read-only and needs no LightRAG. An approval is a review judgement, not a factual
verification, so the report never upgrades confidence or evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sion_api import models
from sqlalchemy import select
from sqlalchemy.orm import Session

from .projection import build_custom_kg, resolve_verification_states

# Same policy as the default projection: approved/machine-verified and pending relations;
# /review-rejected relations only on request (audit/debug).
DEFAULT_REPORT_REVIEW_STATES = ("verified", "unverified")
AUDIT_REPORT_REVIEW_STATES = ("verified", "unverified", "rejected")
REVIEW_BATCH_EVENT = "review.batch_decided"
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


def build_review_report(
    session: Session,
    *,
    review_states: Iterable[str] | None = DEFAULT_REPORT_REVIEW_STATES,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Return the review verification report for the projection filtered by ``review_states``."""
    states = None if review_states is None else tuple(review_states)
    allowed = resolve_verification_states(states)
    kg = build_custom_kg(session, at=at, review_states=states)
    projected = {rel["source_id"]: rel["weight"] for rel in kg["relationships"]}

    # Current relations only (same validity window as the projection, which ignores state here).
    current = build_custom_kg(session, at=at, review_states=None)["relationships"]
    current_keys = {rel["source_id"] for rel in current}

    counts: dict[str, dict[str, int]] = {}
    relations: list[dict[str, Any]] = []
    batch_relations: dict[str, list[str]] = {}
    for row in session.scalars(select(models.Relation).order_by(models.Relation.stable_key)):
        alias = f"sion:relation:{row.stable_key}"
        if alias not in current_keys:
            continue
        bucket = counts.setdefault(row.verification_state, {"total": 0, "projected": 0})
        bucket["total"] += 1
        if alias in projected:
            bucket["projected"] += 1
        properties = row.properties or {}
        review = _pick(properties.get("review"), _REVIEW_FIELDS)
        history = [h for h in (_pick(item, _HISTORY_FIELDS) for item in properties.get("review_history") or []) if h]
        if review is None and not history:
            continue
        if review and review.get("batch_id"):
            batch_relations.setdefault(str(review["batch_id"]), []).append(row.stable_key)
        relations.append({
            "stable_key": row.stable_key,
            "verification_state": row.verification_state,
            "confidence": row.confidence,
            "projected": alias in projected,
            "weight": projected.get(alias),
            "review": review,
            "review_history": history,
        })

    batches: list[dict[str, Any]] = []
    seen: set[str] = set()
    events = session.scalars(
        select(models.OutboxEvent)
        .where(models.OutboxEvent.event_type == REVIEW_BATCH_EVENT)
        .order_by(models.OutboxEvent.created_at, models.OutboxEvent.id)
    )
    for event in events:
        payload = event.payload or {}
        batch_id = str(payload.get("batch_id") or event.aggregate_id)
        seen.add(batch_id)
        batches.append({
            "batch_id": batch_id,
            "decision": payload.get("decision"),
            "reviewer": payload.get("reviewer"),
            "note": payload.get("note"),
            "decided_at": payload.get("decided_at"),
            "counts": payload.get("counts"),
            "results": payload.get("results", []),
            "current_relations": sorted(batch_relations.get(batch_id, [])),
        })
    for batch_id in sorted(set(batch_relations) - seen):  # decided before batch events existed
        batches.append({
            "batch_id": batch_id,
            "decision": None,
            "reviewer": None,
            "note": None,
            "decided_at": None,
            "counts": None,
            "results": [],
            "current_relations": sorted(batch_relations[batch_id]),
        })

    return {
        "canonical": False,
        "review_states": None if states is None else list(states),
        "projected_states": None if allowed is None else sorted(allowed),
        "fact_verification": False,
        "notice": FACT_VERIFICATION_NOTICE,
        "counts": dict(sorted(counts.items())),
        "relations": relations,
        "batches": batches,
    }
