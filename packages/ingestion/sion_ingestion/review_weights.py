"""Ranking weights from human /review decisions (Issue #80).

An approve or reject does not verify a fact and does not change the extracted
``confidence``. It casts one vote on each extraction rule (``properties.rules``)
and guideline predicate (``properties.predicate``) of that candidate. Later
candidates that share a key are ranked with a bounded multiplier:

    multiplier = clamp(1 + 0.05 * (approvals - rejections), 0.75, 1.25)

The ledger is a fold of ``relation.updated`` outbox events, not a counter that
grows on every write. The latest event for a relation wins (highest
``review_rev``, then ``created_at``). Reopening writes a newer event whose
``review_effect`` is ``none``, so that relation's vote drops out. Approving the
same relation again still counts as one vote. Nothing in this module sets
``verification_state``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sion_api import models
from sqlalchemy import select
from sqlalchemy.orm import Session

RULE_PREFIX = "rule:"
GUIDELINE_PREFIX = "guideline:"

# Integer thousandths keep the multiplier exact: 50 = 0.05, 750 = 0.75, 1250 = 1.25.
_NEUTRAL = 1000
_STEP = 50
_MIN = 750
_MAX = 1250
MAX_WEIGHT_SOURCES = 25

STEP = 0.05
MIN_MULTIPLIER = 0.75
MAX_MULTIPLIER = 1.25

NOTICE = (
    "A /review decision changes only the ranking score of later candidates that share this "
    "extraction rule or guideline predicate, by a bounded multiplier. It does not verify the "
    "candidate or the underlying fact, and it does not overwrite extracted confidence or evidence. "
    "Reopening the decision removes its vote."
)

_EFFECTS = frozenset({"approve", "reject", "none"})
_REVIEW_FIELDS = ("decision", "reviewer", "note", "batch_id", "decided_at")


def weight_policy() -> dict[str, Any]:
    """Public description of the multiplier. ``auto_verifies`` is always false."""
    return {
        "step": STEP,
        "min_multiplier": MIN_MULTIPLIER,
        "max_multiplier": MAX_MULTIPLIER,
        "auto_verifies": False,
        "reversible": True,
        "notice": NOTICE,
    }


def weight_keys(properties: dict[str, Any] | None) -> list[str]:
    """Stable keys a candidate votes on, rules first, then the guideline predicate."""
    props = properties or {}
    rules = props.get("rules")
    if not isinstance(rules, list):
        rule = props.get("rule")
        rules = [rule] if isinstance(rule, str) else []
    keys: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        if key not in seen:
            seen.add(key)
            keys.append(key)

    for rule in rules:
        if isinstance(rule, str) and rule.strip():
            add(f"{RULE_PREFIX}{rule.strip()}")
    predicate = props.get("predicate")
    if isinstance(predicate, str) and predicate.strip():
        add(f"{GUIDELINE_PREFIX}{predicate.strip()}")
    return keys


def primary_key(properties: dict[str, Any] | None) -> str | None:
    """Key used to rank this candidate: its first rule, else its guideline predicate."""
    keys = weight_keys(properties)
    return keys[0] if keys else None


def _review_rev(properties: dict[str, Any] | None) -> int:
    value = (properties or {}).get("review_rev")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def relation_event_fields(verification_state: str, properties: dict[str, Any] | None) -> dict[str, Any]:
    """Extra ``relation.updated`` payload for a /review candidate, or ``{}`` when it cannot vote.

    Only a candidate (or a row that still has review metadata) participates. A
    ``human_verified`` row votes only when ``properties.review.decision`` is
    ``approved``; a direct fact write does not.
    """
    props = properties or {}
    review = props.get("review") if isinstance(props.get("review"), dict) else None
    history = props.get("review_history")
    candidate = bool(props.get("candidate"))
    if not candidate and review is None and not history:
        return {}
    if verification_state == "human_verified" and review and review.get("decision") == "approved":
        effect = "approve"
    elif verification_state == "rejected" and review and review.get("decision") == "rejected":
        effect = "reject"
    else:
        effect = "none"
    picked = None
    if review is not None:
        picked = {field: review.get(field) for field in _REVIEW_FIELDS}
    return {
        "candidate": candidate,
        "weight_keys": weight_keys(props),
        "review_effect": effect,
        "review_rev": _review_rev(props),
        "review": picked,
    }


@dataclass(frozen=True)
class ActiveVote:
    relation_id: str
    effect: str
    decision: str
    reviewer: str | None
    note: str | None
    batch_id: str | None
    decided_at: str | None
    event_id: str
    review_rev: int


class ExtractionLedger:
    """Latest active vote per relation, grouped by weight key."""

    def __init__(self, votes: dict[str, tuple[ActiveVote, ...]]) -> None:
        self.votes = votes

    def contribution(self, key: str | None) -> tuple[int, bool, tuple[ActiveVote, ...], tuple[ActiveVote, ...]]:
        """Return ``(multiplier_thousandths, capped, approvals, rejections)``."""
        if not key:
            return _NEUTRAL, False, (), ()
        approvals = tuple(vote for vote in self.votes.get(key, ()) if vote.effect == "approve")
        rejections = tuple(vote for vote in self.votes.get(key, ()) if vote.effect == "reject")
        raw = _NEUTRAL + _STEP * (len(approvals) - len(rejections))
        capped = raw < _MIN or raw > _MAX
        return min(_MAX, max(_MIN, raw)), capped, approvals, rejections


def _payload_rev(payload: dict[str, Any]) -> int:
    value = payload.get("review_rev")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _event_order(event: Any) -> tuple:
    payload = event.payload or {}
    created = getattr(event, "created_at", None)
    return (_payload_rev(payload), created is not None, created or "", str(getattr(event, "id", "")))


def fold_extraction_ledger(events: Iterable[Any]) -> ExtractionLedger:
    """Fold outbox events. Only the latest ``relation.updated`` per relation can vote."""
    latest: dict[str, Any] = {}
    for event in events:
        if getattr(event, "event_type", None) != "relation.updated":
            continue
        payload = event.payload or {}
        if payload.get("review_effect") not in _EFFECTS:
            continue
        relation_id = str(event.aggregate_id)
        current = latest.get(relation_id)
        if current is None or _event_order(event) >= _event_order(current):
            latest[relation_id] = event

    grouped: dict[str, list[ActiveVote]] = {}
    for relation_id, event in latest.items():
        payload = event.payload or {}
        effect = payload["review_effect"]
        if effect == "none":
            continue
        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        decision = review.get("decision")
        if decision not in {"approved", "rejected"}:
            decision = "approved" if effect == "approve" else "rejected"
        vote = ActiveVote(
            relation_id=relation_id,
            effect=effect,
            decision=str(decision),
            reviewer=review.get("reviewer"),
            note=review.get("note"),
            batch_id=review.get("batch_id"),
            decided_at=review.get("decided_at"),
            event_id=str(event.id),
            review_rev=_payload_rev(payload),
        )
        keys = []
        seen: set[str] = set()
        for key in payload.get("weight_keys") or []:
            if isinstance(key, str) and key not in seen:
                seen.add(key)
                keys.append(key)
        for key in keys:
            grouped.setdefault(key, []).append(vote)
    votes = {key: tuple(sorted(items, key=lambda vote: vote.relation_id)) for key, items in grouped.items()}
    return ExtractionLedger(votes)


def load_extraction_ledger(session: Session) -> ExtractionLedger:
    """Replay every ``relation.updated`` event. Acknowledged rows stay in the audit log."""
    rows = session.scalars(
        select(models.OutboxEvent)
        .where(models.OutboxEvent.event_type == "relation.updated")
        .order_by(models.OutboxEvent.created_at, models.OutboxEvent.id)
    )
    return fold_extraction_ledger(rows)


def _multiplier(thousandths: int) -> float:
    return round(thousandths / 1000, 3)


def _same_number(left: Any, right: Any) -> bool:
    """Three-decimal equality so a JSON round-trip of the stored snapshot still matches."""
    if left is None or right is None:
        return left is right
    return round(float(left), 3) == round(float(right), 3)


def ranking_score(confidence: float | None, thousandths: int) -> float | None:
    """Ranking score in ``[0, 1]``. ``None`` when the extractor recorded no confidence."""
    if confidence is None:
        return None
    clamped = min(max(float(confidence), 0.0), 1.0)
    return round(min(max(clamped * thousandths / 1000, 0.0), 1.0), 3)


def rank_value(confidence: float | None, properties: dict[str, Any] | None, ledger: ExtractionLedger) -> float | None:
    """Unrounded sort key. With a neutral ledger this is the clamped confidence."""
    if confidence is None:
        return None
    thousandths, _capped, _approvals, _rejections = ledger.contribution(primary_key(properties))
    clamped = min(max(float(confidence), 0.0), 1.0)
    return clamped * thousandths / 1000


def rank_tuple(
    confidence: float | None,
    properties: dict[str, Any] | None,
    ledger: ExtractionLedger,
    created_at: Any,
    relation_id: Any,
) -> tuple:
    """Pending-queue order: higher score first, null confidence first, then creation time and id.

    A neutral multiplier leaves this equal to ordering by confidence alone.
    """
    value = rank_value(confidence, properties, ledger)
    return (
        value is not None,
        -(value if value is not None else 0.0),
        created_at is None,
        "" if created_at is None else created_at,
        str(relation_id),
    )


def _source(vote: ActiveVote) -> dict[str, Any]:
    return {
        "relation_id": vote.relation_id,
        "event_id": vote.event_id,
        "decision": vote.decision,
        "reviewer": vote.reviewer,
        "note": vote.note,
        "batch_id": vote.batch_id,
        "decided_at": vote.decided_at,
        "review_rev": vote.review_rev,
    }


def describe_score(
    confidence: float | None,
    properties: dict[str, Any] | None,
    ledger: ExtractionLedger,
    *,
    recorded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Live ranking explanation for one candidate. Does not read or write ``confidence``."""
    key = primary_key(properties)
    thousandths, capped, approvals, rejections = ledger.contribution(key)
    active = approvals + rejections
    multiplier = _multiplier(thousandths)
    recorded_summary = None
    matches = None
    if recorded is not None:
        recorded_summary = {
            "key": recorded.get("key"),
            "multiplier": recorded.get("multiplier"),
            "score": recorded.get("score"),
            "approvals": recorded.get("approvals"),
            "rejections": recorded.get("rejections"),
        }
        matches = (
            recorded.get("key") == key
            and _same_number(recorded.get("multiplier"), multiplier)
            and recorded.get("approvals") == len(approvals)
            and recorded.get("rejections") == len(rejections)
        )
    kind = None
    label = None
    if key and key.startswith(GUIDELINE_PREFIX):
        kind, label = "guideline", key[len(GUIDELINE_PREFIX) :]
    elif key and key.startswith(RULE_PREFIX):
        kind, label = "rule", key[len(RULE_PREFIX) :]
    return {
        "key": key,
        "kind": kind,
        "label": label,
        "base_confidence": confidence,
        "multiplier": multiplier,
        "score": ranking_score(confidence, thousandths),
        "approvals": len(approvals),
        "rejections": len(rejections),
        "capped": capped,
        "sources": [_source(vote) for vote in active[:MAX_WEIGHT_SOURCES]],
        "source_count": len(active),
        "auto_verifies": False,
        "reversible": True,
        "notice": NOTICE,
        "recorded_at_extraction": recorded_summary,
        "snapshot_matches_live": matches,
    }
