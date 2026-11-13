# Sion API authorization

This page describes how `apps/api` (`sion_api`) authorizes requests. The policy lives in
`apps/api/sion_api/auth.py`; route coverage is enforced by `tests/test_api_scopes.py`.

The policy is provider-neutral. It authorizes opaque bearer tokens mapped to scopes and an
optional project allowlist. For hosted deployments it can also verify identity-provider access
tokens (OIDC JWTs, Supabase Auth by default) locally against the issuer's JWKS; see
[OIDC user tokens](#oidc-user-tokens) and [`SAAS.md`](SAAS.md). A Cloudflare Access gate or a
reverse proxy can still map credentials onto this policy without changing route code.

## Modes

`SION_API_AUTH_MODE` selects one of three modes:

| Mode | Trusted loopback request | Remote request |
| --- | --- | --- |
| `local-only` (default) | allowed, all scopes, all projects | 403 |
| `local-or-bearer` | allowed, all scopes, all projects | bearer token required |
| `bearer` | bearer token required | bearer token required |

A trusted loopback request needs a loopback peer address, a `localhost`, `127.0.0.1` or `::1`
`Host` header and a same-origin or explicitly trusted `Origin` (`SION_CORS_ORIGINS`).
Cross-site browser requests are rejected before the body or database is touched.

## Tokens

`SION_API_TOKENS_JSON` maps each token (at least 16 characters) to a grant. Two forms are
accepted:

```json
{
  "replace-with-reader-token": ["read:knowledge", "read:aec"],
  "replace-with-reviewer-token": ["read:knowledge", "write:knowledge"],
  "replace-with-mobile-token": {
    "scopes": ["read:knowledge", "write:knowledge"],
    "projects": ["00000000-0000-0000-0000-000000000000"]
  },
  "replace-with-admin-token": ["*"]
}
```

The list form is the original format and remains valid. It grants access to all projects.
The object form accepts only `scopes` and `projects`. `projects` must be a non-empty list
of project UUIDs. Any malformed entry stops the server at startup. Configuration errors
never quote the token or the raw JSON document.

## Scopes

| Scope | Grants |
| --- | --- |
| `read:knowledge` | Every read-only knowledge route: schema, inventories, entities, relations, candidate queues, evidence, graph, artifacts, outbox reads, vector search, GraphRAG status and query, contracts, storage status, law search, regulation status, evaluation and works reads, SHACL validation. |
| `write:knowledge` | Every write: entity, relation and evidence writes, embeddings, artifacts, relation review decisions (approve, reject, reopen, bulk), imports and ingestion, relation extraction, GraphRAG projection, storage export, outbox acknowledgement, law article upserts, regulation work saves and updates. |
| `read:aec` | AEC/CAIR federation status and queries. |
| `*` | All scopes. |

Scopes are disjoint. `write:knowledge` does not imply `read:knowledge`. A reviewer that reads
candidates and records decisions needs both scopes.

A handful of `POST` routes compute an answer without persisting anything. They require
`read:knowledge`: `/api/v1/vector/search`, `/api/v1/analyze/dxf`, `/api/v1/graphrag/query`,
`/api/v1/regulation/evaluate` and `/api/v1/regulation/gateway/report`.

Public routes without authorization are limited to `/health`, the static `/review` and `/map`
HTML shells (their data calls are scoped), the FastAPI schema and docs pages, and the Paddle
webhook, which is authenticated by its HMAC signature instead of a bearer token.

## Project ACL

A token with a `projects` allowlist is project-restricted:

- It may call only routes declared project-scoped. These routes apply the ACL themselves
  through `require_project_access()` or `allowed_projects()`. All other routes return 403 for
  such a token, because they could return cross-project data.
- The ACL is checked before project data is returned or written. For a save, it is checked
  before the project lookup or any gateway call.
- A project outside the allowlist answers 404, the same as a missing project, so a restricted
  token cannot probe for other projects.
- Lists without a `project_id` filter return only the allowed projects.

Project-scoped routes today are `/regulation`, `/api/v1/regulation/works*`,
`/api/v1/regulation/summary`, `/api/v1/me`, `/api/v1/billing/me`, and the knowledge reads
`GET /api/v1/entities`, `/api/v1/entities/{id}`, `/api/v1/relations` and `/api/v1/graph`, the
project writes listed below, and `/api/v1/projects/{project_id}/documents`.

For the knowledge reads, an entity belongs to a project when it **is** the `Project` entity or
its `properties.project_id` names it (the convention regulation works already use). A relation
is visible only when both of its endpoints are, so an edge never reveals an entity outside the
caller's projects. These routes also take an optional `project_id` filter; asking for a project
outside the allowlist answers 404. Unscoped entities (no `project_id`) are visible only to
unrestricted callers.

Project-restricted callers with `write:knowledge` may also write inside their projects
(`sion_api.project_writes`):

- `POST /api/v1/entities` needs `properties.project_id` on the allowlist; creating a `Project`
  entity answers 403 (projects are created by an unrestricted caller).
- `PATCH /api/v1/entities/{id}` edits `name`, `description`, `category` and `properties` (a JSON
  merge patch, `null` removes a key) of a visible entity. Restricted callers cannot change
  `properties.project_id`, so data never moves between projects.
- `POST /api/v1/relations` needs both endpoints visible; `POST /api/v1/relations/{id}/invalidate`
  and `POST /api/v1/evidence` need the relation or entity visible. Anything else answers 404.
- `POST /api/v1/projects/{project_id}/documents?filename=<name>` takes the file as the raw
  request body, stores it under `SION_UPLOAD_ROOT/<project_id>/` (default `runtime/uploads`,
  limit `SION_UPLOAD_MAX_BYTES`, default 25 MiB) and ingests it with every node stamped with the
  project. Re-uploading the same bytes reuses the same document. `GET` on the same path lists
  the project's documents. Server paths are never returned.

To make a new route project-scoped, wrap its scope dependency with `project_scoped()` and call
`require_project_access()` or `allowed_projects()` in the handler. Then add the route to
`PROJECT_SCOPED_ROUTES` in `tests/test_api_scopes.py`.

Routes that return only tenant-independent data are marked `shared_reference()` and are open to
restricted callers too: `GET /api/v1/schema/ontology`, `/api/v1/law/search` and
`/api/v1/law/articles/{law_id}/{article_key}` (published law text). Only add a route there when
its response can never contain project data; they are listed in `SHARED_REFERENCE_ROUTES`.

Trusted local access and tokens without `projects` are unrestricted.

## OIDC user tokens

Set `SION_OIDC_ISSUER` (install the `saas` extra) and a bearer value that is not a configured
static token is verified as a JWT from that issuer. `bearer` modes then start without
`SION_API_TOKENS_JSON`. Verification is local: signature against the issuer's JWKS (cached ten
minutes; asymmetric algorithms only), `iss`, `aud` (default `authenticated`), `exp`/`nbf` with
30 s leeway, and a required `sub`.

A verified token becomes `Principal(kind="user", subject=<sub>)`:

- Scopes are `SION_OIDC_DEFAULT_SCOPES` (default `read:knowledge`) plus the list at
  `SION_OIDC_SCOPES_CLAIM` (default `app_metadata.sion_scopes`). `*` from a claim is dropped.
- Projects come from `SION_OIDC_PROJECTS_CLAIM` (default `app_metadata.sion_projects`). A token
  without the claim is restricted to **no** projects; malformed ids are dropped. Only an explicit
  `"*"` entry makes a user unrestricted. In Supabase, `app_metadata` is writable only with the
  service role, so users cannot grant themselves projects.
- Users are therefore project-restricted and reach only project-scoped routes, including
  `GET /api/v1/me` (the caller's identity) and `GET /api/v1/billing/me`.
- Per-client throttling keys on a digest of `sub`.

## Token handling

- Tokens are compared in constant time against every configured token.
- Responses never echo a token. Error details name only the missing scope.
- The authorized `Principal` (on `request.state.sion_principal`) carries the scopes and
  projects, not the token.
- `sion_api` does not log request headers. Tests assert that tokens appear in neither
  responses nor captured logs.
- Outbound credentials such as `GATEWAY_TOKEN` are sent only to their configured service.

## Route coverage test

`tests/test_api_scopes.py` enumerates every route of the FastAPI app and fails when:

- a route has no `require_scope` dependency and is not in `PUBLIC_ROUTES`;
- a mutating route (`POST`, `PUT`, `PATCH`, `DELETE`) lacks a `write:*` scope and is not in
  `READ_ONLY_POSTS`;
- a `GET` route lacks a `read:*` scope;
- the set of project-scoped routes differs from `PROJECT_SCOPED_ROUTES`.

It also calls every route with a read-only token, a write-only token and no token, and checks
the expected 403 or 401. Changing an allowlist requires a justification comment and review.
