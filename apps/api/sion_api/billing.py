"""Paddle Billing webhooks -> subscription entitlements (hosted deployments only).

Paddle is the merchant of record: it owns checkout, invoices, tax and refunds. Sion only keeps
the minimum it needs to gate features: one row per Paddle subscription with its status, price
ids and the Sion user it belongs to. The link to the user comes from ``custom_data.sion_user_id``,
which the web app passes to Paddle checkout (the OIDC ``sub`` of the signed-in user).

Webhook security
* ``Paddle-Signature: ts=<unix>;h1=<hex>`` is HMAC-SHA256 over ``"<ts>:<raw body>"`` with the
  notification destination's secret key. Several ``h1`` values may be present while a secret is
  rotated; any match is accepted. Comparison is constant time.
* ``ts`` must be within ``SION_PADDLE_TOLERANCE_SECONDS`` (default 300) of now (replay window).
* ``event_id`` is stored, so a retried delivery is acknowledged without being applied twice.
* Events are applied only if newer than the last one applied to that subscription
  (``occurred_at``), because Paddle does not guarantee delivery order.

No customer names, emails or addresses are stored, and the raw payload is not kept.

Environment
* ``SION_PADDLE_WEBHOOK_SECRET``  notification destination secret (webhook returns 503 without it)
* ``SION_PADDLE_TOLERANCE_SECONDS``  replay window, default 300
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import current_principal
from .db import Base

ACTIVE_STATUSES = frozenset({"active", "trialing", "past_due"})
SUBSCRIPTION_EVENTS = frozenset(
    {
        "subscription.created",
        "subscription.updated",
        "subscription.activated",
        "subscription.trialing",
        "subscription.past_due",
        "subscription.paused",
        "subscription.resumed",
        "subscription.canceled",
        "subscription.imported",
    }
)
MAX_BODY_BYTES = 1_000_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillingEvent(Base):
    """Processed webhook deliveries (idempotency ledger)."""

    __tablename__ = "billing_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class BillingSubscription(Base):
    __tablename__ = "billing_subscriptions"

    subscription_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    price_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    product_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_change: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SignatureError(ValueError):
    pass


def verify_signature(header: str | None, body: bytes, secret: str, *, tolerance: int = 300,
                     now: float | None = None) -> None:
    """Raise :class:`SignatureError` unless ``header`` is a fresh, valid Paddle signature."""
    if not header:
        raise SignatureError("missing Paddle-Signature header")
    ts: str | None = None
    candidates: list[str] = []
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "ts":
            ts = value
        elif key == "h1" and value:
            candidates.append(value.lower())
    if ts is None or not ts.isdigit() or not candidates:
        raise SignatureError("malformed Paddle-Signature header")
    current = time.time() if now is None else now
    if abs(current - int(ts)) > tolerance:
        raise SignatureError("signature timestamp outside the replay window")
    expected = hmac.new(secret.encode("utf-8"), ts.encode("ascii") + b":" + body, hashlib.sha256).hexdigest()
    matched = False
    for candidate in candidates:
        matched |= hmac.compare_digest(expected, candidate)
    if not matched:
        raise SignatureError("signature mismatch")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone=True columns.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _short(value: Any, limit: int = 64) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def apply_event(session: Session, event: dict[str, Any]) -> str:
    """Apply one verified Paddle event. Returns processed, duplicate, ignored or stale."""
    event_id = _short(event.get("event_id"))
    event_type = _short(event.get("event_type"), 80)
    occurred_at = _parse_time(event.get("occurred_at"))
    data = event.get("data")
    if event_id is None or event_type is None or occurred_at is None or not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="event_id, event_type, occurred_at and data are required")
    if session.get(BillingEvent, event_id) is not None:
        return "duplicate"

    outcome = "ignored"
    if event_type in SUBSCRIPTION_EVENTS:
        outcome = _apply_subscription(session, data, occurred_at)
    session.add(BillingEvent(event_id=event_id, event_type=event_type, occurred_at=occurred_at, outcome=outcome))
    try:
        session.commit()
    except IntegrityError:  # a concurrent delivery of the same event won the race
        session.rollback()
        return "duplicate"
    return outcome


def _apply_subscription(session: Session, data: dict[str, Any], occurred_at: datetime) -> str:
    subscription_id = _short(data.get("id"))
    status = _short(data.get("status"), 32)
    if subscription_id is None or status is None:
        raise HTTPException(status_code=400, detail="subscription event without id or status")
    row = session.get(BillingSubscription, subscription_id)
    if row is not None and _aware(row.last_event_at) > occurred_at:
        return "stale"

    items = data.get("items") if isinstance(data.get("items"), list) else []
    prices = [item.get("price") for item in items if isinstance(item, dict) and isinstance(item.get("price"), dict)]
    price_ids = sorted({p["id"] for p in prices if isinstance(p.get("id"), str)})
    product_ids = sorted({p["product_id"] for p in prices if isinstance(p.get("product_id"), str)})
    period = data.get("current_billing_period") if isinstance(data.get("current_billing_period"), dict) else {}
    scheduled = data.get("scheduled_change") if isinstance(data.get("scheduled_change"), dict) else {}
    custom = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
    subject = _short(custom.get("sion_user_id"), 255)

    if row is None:
        row = BillingSubscription(subscription_id=subscription_id, status=status, last_event_at=occurred_at)
        session.add(row)
    row.customer_id = _short(data.get("customer_id")) or row.customer_id
    # custom_data can be edited in Paddle; never drop an existing link because an event omits it.
    row.user_subject = subject or row.user_subject
    row.status = status
    row.price_ids = price_ids or list(row.price_ids or [])
    row.product_ids = product_ids or list(row.product_ids or [])
    row.current_period_end = _parse_time(period.get("ends_at"))
    row.scheduled_change = _short(scheduled.get("action"), 32)
    row.last_event_at = occurred_at
    row.updated_at = _utcnow()
    return "processed"


def entitlements_for(session: Session, subject: str) -> dict[str, Any]:
    rows = session.scalars(
        select(BillingSubscription)
        .where(BillingSubscription.user_subject == subject)
        .order_by(BillingSubscription.last_event_at.desc())
    ).all()
    subscriptions = [
        {
            "subscription_id": row.subscription_id,
            "status": row.status,
            "active": row.status in ACTIVE_STATUSES,
            "price_ids": list(row.price_ids or []),
            "product_ids": list(row.product_ids or []),
            "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
            "scheduled_change": row.scheduled_change,
        }
        for row in rows
    ]
    return {
        "active": any(item["active"] for item in subscriptions),
        "price_ids": sorted({pid for item in subscriptions if item["active"] for pid in item["price_ids"]}),
        "subscriptions": subscriptions,
    }


def register(app: FastAPI, get_session, read_dep) -> None:
    @app.post("/api/v1/billing/paddle/webhook", include_in_schema=False)
    async def paddle_webhook(request: Request, session: Session = Depends(get_session)):
        secret = os.getenv("SION_PADDLE_WEBHOOK_SECRET", "")
        if not secret:
            raise HTTPException(status_code=503, detail="billing webhooks are not configured")
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
        tolerance = int(os.getenv("SION_PADDLE_TOLERANCE_SECONDS", "300") or 300)
        try:
            verify_signature(request.headers.get("Paddle-Signature"), body, secret, tolerance=tolerance)
        except SignatureError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from None
        try:
            event = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="body is not JSON") from None
        if not isinstance(event, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        return {"status": await anyio.to_thread.run_sync(apply_event, session, event)}

    @app.get("/api/v1/me", dependencies=[Depends(read_dep)])
    def whoami(request: Request):
        """The caller as the API sees it (for the web app's session check). Never echoes a token."""
        principal = current_principal(request)
        return {
            "kind": principal.kind,
            "subject": principal.subject,
            "scopes": sorted(principal.scopes),
            "projects": None if principal.projects is None else sorted(principal.projects),
        }

    @app.get("/api/v1/billing/me", dependencies=[Depends(read_dep)])
    def billing_me(request: Request, session: Session = Depends(get_session)):
        principal = current_principal(request)
        if principal.kind != "user" or not principal.subject:
            raise HTTPException(status_code=404, detail="billing is tied to signed-in users")
        return {"subject": principal.subject, **entitlements_for(session, principal.subject)}

