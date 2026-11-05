# Sion Ontology API

Free/open-source API layer for the Sion knowledge graph.

## Development

Create an isolated environment outside the repository when possible:

```bash
python3 -m venv /tmp/sion-api-venv
/tmp/sion-api-venv/bin/pip install -e '.[test]'
SION_DATABASE_URL=sqlite:////tmp/sion-api.db \
  /tmp/sion-api-venv/bin/uvicorn sion_api.main:app \
  --app-dir apps/api --host 127.0.0.1 --port 3012
```

PostgreSQL is the canonical production target:

```text
SION_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB
SION_AUTO_CREATE_SCHEMA=0
```

Production PostgreSQL uses the SQL migrations under `migrations/`.
SQLite exists only for local smoke tests and does not replace PostgreSQL as
the canonical deployment database.

## Operations

- `GET /health/live` - liveness probe (no auth, no database access).
- `GET /health/ready` - readiness probe: read-only `SELECT 1`; returns `503` with
  `{"checks": {"database": "unavailable"}}` and no connection details on failure.
- Structured access log: one JSON line per request on the `sion_api.access` logger
  (method, path without query string, status, duration, `X-Request-ID`). Headers,
  query strings and bodies are never logged. Disable with `SION_API_ACCESS_LOG=0`.

Runbook (health checks, logs, backup/restore, cost caps, deploy flow):
[`docs/ops/CLOUD-OPS.ko.md`](../../docs/ops/CLOUD-OPS.ko.md).
