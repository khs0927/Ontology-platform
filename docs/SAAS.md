# Hosted (SaaS) mode: sign-in and billing

Phase 7 of the stack upgrade (stack decision of 2026-11-12) turns the local engine into a hosted
service without changing the self-hosted defaults. Self-hosted installs keep `local-only` or
static bearer tokens and never need anything on this page.

| Concern | Choice | Where |
| --- | --- | --- |
| Sign-in | Supabase Auth (any OIDC issuer with a JWKS works) | `sion_api/oidc.py`, `sion_api/auth.py` |
| Billing | Paddle Billing (merchant of record: tax, invoices, refunds) | `sion_api/billing.py` |
| Entitlements | `billing_subscriptions` + `billing_events` tables | `migrations/010_billing.sql` |
| Web app | Next.js 16 (separate PR) | `apps/web` |

## Sign-in (OIDC)

```bash
pip install 'sion-ontology-platform[saas]'
export SION_API_AUTH_MODE=bearer                      # or local-or-bearer for a dev box
export SION_OIDC_ISSUER=https://<project-ref>.supabase.co/auth/v1
# optional
export SION_OIDC_AUDIENCE=authenticated               # Supabase default
export SION_OIDC_DEFAULT_SCOPES="read:knowledge"
export SION_OIDC_SCOPES_CLAIM=app_metadata.sion_scopes
export SION_OIDC_PROJECTS_CLAIM=app_metadata.sion_projects
```

The browser signs in with Supabase and sends its access token as `Authorization: Bearer <jwt>`.
The API verifies it locally against `<issuer>/.well-known/jwks.json`; no call to Supabase per
request. Supabase projects must use **asymmetric JWT signing keys** (ES256/RS256): legacy HS256
shared-secret tokens are refused on purpose.

Grant a user projects or extra scopes from a trusted backend with the service role, e.g.
`auth.admin.updateUserById(id, { app_metadata: { sion_projects: ["<uuid>"], sion_scopes: ["write:knowledge"] } })`.
The rules (fail-closed projects, no `*` scope from claims) are in
[`API_AUTH.md`](API_AUTH.md#oidc-user-tokens). `GET /api/v1/me` returns what the API sees.

Static tokens keep working next to OIDC (for CI, the MCP server and service accounts).

## Billing (Paddle)

1. In Paddle, create a notification destination for
   `https://<api-host>/api/v1/billing/paddle/webhook` with the `subscription.*` events.
2. Put its secret key in `SION_PADDLE_WEBHOOK_SECRET`. Without it the webhook answers 503.
3. The web app opens Paddle checkout with `customData: { sion_user_id: <supabase user id> }`;
   Paddle copies it to the subscription, which links the subscription to the signed-in user.

The webhook verifies `Paddle-Signature` (HMAC-SHA256 over `ts:raw_body`, any `h1` during secret
rotation, `SION_PADDLE_TOLERANCE_SECONDS` replay window, default 300), records each `event_id`
once, and applies an event only when it is newer than the last one for that subscription,
because Paddle does not guarantee order. Responses: `processed`, `duplicate`, `stale` or
`ignored` (non-subscription events). Only ids, status, price/product ids and billing-period end
are stored: no names, emails, addresses or raw payloads.

`GET /api/v1/billing/me` (signed-in users) returns `active` (any subscription `active`,
`trialing` or `past_due`), the active price ids and each subscription.

## Plan entitlements

Map Paddle prices to extra API scopes:

```bash
export SION_PLAN_SCOPES_JSON='{"pri_pro_monthly": ["write:knowledge", "read:aec"]}'
```

A signed-in user with an `active`, `trialing` or `past_due` subscription to a listed price gets
those scopes on top of `SION_OIDC_DEFAULT_SCOPES`; `GET /api/v1/me` shows the result. Lookups are
cached for 60 s per user and the cache is cleared whenever a webhook changes a subscription, so
an upgrade or cancellation applies on the next request. A plan can never grant `*`, and a lookup
error grants nothing. Scopes still sit inside the project ACL: a plan widens *what* a user may do,
never *which projects* they see.

## Not in this slice

- Usage metering and quotas.
- Tenant/organization objects and row-level security on knowledge tables. Users are scoped to
  projects through the project ACL: entity, relation and graph reads filter to their projects,
  law search and the ontology schema are shared, users with `write:knowledge` can upload
  documents into their projects and edit their entities, relations and evidence (see
  `docs/API_AUTH.md`), review their projects' candidate relations, read their evidence and run vector search over
  them, and the remaining knowledge routes (artifacts, review report, GraphRAG, path-based
  ingest) stay closed to them for now.
- Creating a project for a signed-in user. Projects are made by an unrestricted caller and
  granted through the user's projects claim, which depends on the identity provider.
- The Next.js 16 web app (sign-in, dashboard, checkout): next PR.
