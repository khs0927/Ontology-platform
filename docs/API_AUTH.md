# Sion API authorization

This page describes how `apps/api` (`sion_api`) authorizes requests. The policy lives in
`apps/api/sion_api/auth.py`; route coverage is enforced by `tests/test_api_scopes.py`.

The policy is provider-neutral. It authorizes opaque bearer tokens mapped to scopes and an
optional project allowlist. An OIDC/OAuth 2.1 front door, a Cloudflare Access gate or a
reverse proxy can issue or map credentials onto this policy without changing route code.
Identity-provider integration is infrastructure work and is not part of this module.

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
HTML shells (their data calls are scoped), and the FastAPI schema and docs pages.

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

Project-scoped routes today are `/regulation` and `/api/v1/regulation/works*`. To make a new
route project-scoped, wrap its scope dependency with `project_scoped()` and call
`require_project_access()` or `allowed_projects()` in the handler. Then add the route to
`PROJECT_SCOPED_ROUTES` in `tests/test_api_scopes.py`.

Trusted local access and tokens without `projects` are unrestricted.

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
