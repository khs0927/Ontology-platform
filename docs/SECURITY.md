# Security model

Ontology Platform is designed for local-first operation and must fail closed when write credentials are not configured.

## API modes

### token — default

`ONTOLOGY_SECURITY_MODE=token` is the default.

Mutating endpoints require:

```text
Authorization: Bearer <ONTOLOGY_API_TOKEN>
```

The token is compared with a constant-time comparison. The API never returns the configured token.

If `ONTOLOGY_API_TOKEN` is absent, write requests return HTTP 503 instead of silently becoming unauthenticated.

### private — all data routes

Use `ONTOLOGY_SECURITY_MODE=private` when graph data and provenance must be
visible only to authenticated clients. Every route except `/health` and
`/health/security` requires the same Bearer token, including `/graph`, Evidence
reads, database health, and the OpenAPI document. Without a configured token,
data requests fail closed with HTTP 503.

### disabled — local/test only

`ONTOLOGY_SECURITY_MODE=disabled` deliberately disables application-layer write authentication.

Use it only for:

- in-memory/local test suites,
- loopback-only development,
- disposable development environments protected by another trusted boundary.

Never use disabled mode on a publicly reachable API.

## Protected operations

The current write guard covers:

- POST `/imports/map`
- POST/PATCH/DELETE entity operations
- POST/DELETE relation operations
- POST artifact registration
- POST/DELETE evidence operations

In default `token` mode, read endpoints remain available so the graph/dashboard
can be separated from write authorization. Set `private` mode for confidential
data or a network exposed instance without a separate read access boundary.

## Secret handling

Do not commit:

- `ONTOLOGY_API_TOKEN`
- PostgreSQL passwords/DSNs
- OAuth tokens
- rclone configuration
- Google credentials
- Doppler tokens
- private keys or certificates

Runtime secrets should be supplied through the execution environment or a secrets manager such as the existing Doppler setup when that execution host is connected.

## Network boundary

Application bearer authentication is not a replacement for the network access layer.

For external access:

1. bind application services to loopback/private interfaces where practical,
2. route through the existing reverse proxy / Cloudflare access boundary,
3. select `private` mode when the reverse proxy does not authenticate read requests,
4. expose only required routes,
5. log authorization failures without logging bearer tokens.

## Health endpoint

`GET /health/security` reports only:

- active security mode,
- whether write authentication is configured.

It never reports secret material.

## Test behavior

The repository test suite opts into `ONTOLOGY_SECURITY_MODE=disabled` explicitly through `tests/conftest.py`. Dedicated security tests instantiate token mode directly and verify fail-closed behavior.
