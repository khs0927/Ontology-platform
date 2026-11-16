from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from sion_api import billing
from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_api.oidc import OidcVerifier

jwt = pytest.importorskip("jwt")
ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")

ISSUER = "https://example-ref.supabase.co/auth/v1"
STATIC = "test-only-static-token-value-0001"
PROJECT = str(uuid.uuid4())
SECRET = "pdl_ntfset_test_only_secret"


@pytest.fixture(scope="module")
def keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


def _token(private, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": "user-123",
        "email": "someone@example.test",
        "iat": now,
        "exp": now + 600,
        "app_metadata": {"sion_scopes": ["write:knowledge", "*"], "sion_projects": [PROJECT, "not-a-uuid"]},
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private, algorithm="ES256", headers={"kid": "k1"})


def _app(public, monkeypatch=None, *, static=True):
    verifier = OidcVerifier(issuer=ISSUER, key_resolver=lambda _token: public)
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=((STATIC, frozenset({"read:knowledge"})),) if static else (),
        oidc=verifier,
    )
    return create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy)


def _me(client, token):
    return client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})


def test_verified_user_token_maps_claims_fail_closed(keypair):
    private, public = keypair
    with TestClient(_app(public)) as client:
        body = _me(client, _token(private)).json()
    assert body["kind"] == "user" and body["subject"] == "user-123"
    # default scope + claim scopes, never "*"
    assert body["scopes"] == ["read:knowledge", "write:knowledge"]
    # malformed project ids are dropped
    assert body["projects"] == [PROJECT]
    assert "email" not in body


def test_token_without_project_claim_sees_no_projects(keypair):
    private, public = keypair
    with TestClient(_app(public)) as client:
        body = _me(client, _token(private, app_metadata={})).json()
    assert body["projects"] == [] and body["scopes"] == ["read:knowledge"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.example/auth/v1"},
        {"aud": "anon"},
        {"exp": int(time.time()) - 3600},
        {"sub": None},
    ],
)
def test_bad_claims_are_rejected(keypair, overrides):
    private, public = keypair
    with TestClient(_app(public)) as client:
        response = _me(client, _token(private, **overrides))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_wrong_key_and_hmac_tokens_are_rejected(keypair):
    _private, public = keypair
    other = ec.generate_private_key(ec.SECP256R1())
    forged_hs = jwt.encode({"iss": ISSUER, "aud": "authenticated", "sub": "x", "exp": int(time.time()) + 60},
                           "shared-secret-value-long-enough-0123456789", algorithm="HS256")
    with TestClient(_app(public)) as client:
        assert _me(client, _token(other)).status_code == 401
        assert _me(client, forged_hs).status_code == 401
        assert _me(client, "not.a.jwt").status_code == 401


def test_static_tokens_keep_working_next_to_oidc(keypair):
    _private, public = keypair
    with TestClient(_app(public)) as client:
        body = _me(client, STATIC).json()
    assert body == {"kind": "bearer", "subject": None, "scopes": ["read:knowledge"], "projects": None}


def test_jwks_fetch_path(keypair):
    private, public = keypair
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(public))
    jwk.update({"kid": "k1", "use": "sig", "alg": "ES256"})
    payload = json.dumps({"keys": [jwk]}).encode()
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/auth/v1/.well-known/jwks.json"
        verifier = OidcVerifier(issuer=ISSUER, jwks_url=url)
        claims = verifier.verify(_token(private))
        verifier.verify(_token(private, sub="user-456"))
    finally:
        server.shutdown()
    assert claims.subject == "user-123" and claims.projects == frozenset({PROJECT})
    assert hits == ["/auth/v1/.well-known/jwks.json"]  # keys are cached


def test_from_env_bearer_mode_accepts_oidc_without_static_tokens(monkeypatch):
    monkeypatch.setenv("SION_API_AUTH_MODE", "bearer")
    monkeypatch.delenv("SION_API_TOKENS_JSON", raising=False)
    monkeypatch.setenv("SION_OIDC_ISSUER", ISSUER + "/")
    monkeypatch.setenv("SION_OIDC_DEFAULT_SCOPES", "read:knowledge read:aec")
    policy = AuthPolicy.from_env()
    assert policy.oidc.issuer == ISSUER
    assert policy.oidc.jwks_url == ISSUER + "/.well-known/jwks.json"
    assert policy.oidc.default_scopes == frozenset({"read:knowledge", "read:aec"})
    monkeypatch.delenv("SION_OIDC_ISSUER")
    with pytest.raises(RuntimeError, match="SION_OIDC_ISSUER"):
        AuthPolicy.from_env()


def test_verifier_refuses_unsafe_configuration():
    with pytest.raises(RuntimeError):
        OidcVerifier(issuer="http://idp.example")
    with pytest.raises(RuntimeError):
        OidcVerifier(issuer=ISSUER, algorithms=("HS256",))
    with pytest.raises(RuntimeError):
        OidcVerifier(issuer=ISSUER, default_scopes=frozenset({"*"}))


def test_client_key_is_per_user(keypair):
    private, public = keypair
    policy = AuthPolicy(mode="bearer", oidc=OidcVerifier(issuer=ISSUER, key_resolver=lambda _t: public))

    class _Req:
        def __init__(self, token):
            self.headers = {"Authorization": f"Bearer {token}"}
            self.client = None
            self.state = type("S", (), {})()

    a = policy.client_key(_Req(_token(private)))
    b = policy.client_key(_Req(_token(private, sub="user-456")))
    assert a.startswith("user:") and a != b and "user-123" not in a


# --- Paddle billing -----------------------------------------------------------------------


def _signed(body: bytes, *, ts: int | None = None, secret: str = SECRET) -> str:
    ts = int(time.time()) if ts is None else ts
    digest = hmac.new(secret.encode(), f"{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


def _event(event_id, status, occurred_at, *, event_type="subscription.updated", user="user-123"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "notification_id": "ntf_test",
        "data": {
            "id": "sub_01test",
            "status": status,
            "customer_id": "ctm_01test",
            "custom_data": {"sion_user_id": user} if user else None,
            "items": [{"price": {"id": "pri_pro_monthly", "product_id": "pro_sion"}, "quantity": 1}],
            "current_billing_period": {"starts_at": "2026-11-01T00:00:00Z", "ends_at": "2026-12-01T00:00:00Z"},
            "scheduled_change": None,
        },
    }


def _post(client, event, *, signature=None):
    body = json.dumps(event).encode()
    return client.post(
        "/api/v1/billing/paddle/webhook",
        content=body,
        headers={"Paddle-Signature": signature or _signed(body), "Content-Type": "application/json"},
    )


def test_signature_verification():
    body = b'{"a":1}'
    now = 1_800_000_000
    good = _signed(body, ts=now)
    billing.verify_signature(good, body, SECRET, now=now)
    # rotation: any matching h1 is accepted
    billing.verify_signature(f"ts={now};h1={'0' * 64};{good.split(';')[1]}", body, SECRET, now=now)
    for header, when in [
        (good, now + 301),  # replay window
        (_signed(body, ts=now, secret="other"), now),
        (good.replace("h1=", "h2="), now),
        ("", now),
    ]:
        with pytest.raises(billing.SignatureError):
            billing.verify_signature(header, body, SECRET, now=when)
    with pytest.raises(billing.SignatureError):
        billing.verify_signature(good, body + b" ", SECRET, now=now)


def test_webhook_requires_configuration_and_valid_signature(keypair, monkeypatch):
    _private, public = keypair
    event = _event("evt_1", "active", "2026-11-12T00:00:00Z")
    with TestClient(_app(public)) as client:
        monkeypatch.delenv("SION_PADDLE_WEBHOOK_SECRET", raising=False)
        assert _post(client, event).status_code == 503
        monkeypatch.setenv("SION_PADDLE_WEBHOOK_SECRET", SECRET)
        assert _post(client, event, signature="ts=1;h1=00").status_code == 401
        assert _post(client, event).json() == {"status": "processed"}


def test_webhook_is_idempotent_and_order_safe(keypair, monkeypatch):
    private, public = keypair
    monkeypatch.setenv("SION_PADDLE_WEBHOOK_SECRET", SECRET)
    user = {"Authorization": f"Bearer {_token(private)}"}
    with TestClient(_app(public)) as client:
        assert _post(client, _event("evt_1", "active", "2026-11-12T00:00:00Z",
                                    event_type="subscription.created")).json()["status"] == "processed"
        assert _post(client, _event("evt_1", "active", "2026-11-12T00:00:00Z")).json()["status"] == "duplicate"
        me = client.get("/api/v1/billing/me", headers=user).json()
        assert me["active"] is True and me["price_ids"] == ["pri_pro_monthly"]

        # a later cancel, then an older update delivered late: the older one must not revive it
        assert _post(client, _event("evt_3", "canceled", "2026-11-12T02:00:00Z", user=None)).json()["status"] == "processed"
        assert _post(client, _event("evt_2", "active", "2026-11-12T01:00:00Z")).json()["status"] == "stale"
        me = client.get("/api/v1/billing/me", headers=user).json()
        assert me["active"] is False
        # the user link survives an event that omits custom_data
        assert me["subscriptions"][0]["status"] == "canceled"

        assert _post(client, {"event_id": "evt_tx", "event_type": "transaction.completed",
                              "occurred_at": "2026-11-12T03:00:00Z", "data": {"id": "txn_1"}}).json() == {
            "status": "ignored"
        }
        assert _post(client, {"event_id": "evt_bad"}).status_code == 400

        # static-token callers have no billing identity
        assert client.get("/api/v1/billing/me", headers={"Authorization": f"Bearer {STATIC}"}).status_code == 404


def test_billing_migration_matches_models():
    from sion_api import migrate

    assert "010_billing" in migrate.CORE_SEQUENCE
    sql = (migrate.CORE_DIR / "010_billing.sql").read_text()
    for table in (billing.BillingEvent.__table__, billing.BillingSubscription.__table__):
        assert f"CREATE TABLE IF NOT EXISTS {table.name}" in sql
        for column in table.columns:
            assert f"  {column.name} " in sql, column.name
