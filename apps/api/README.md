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

Production PostgreSQL uses the SQL migrations under `migrations/`. Alembic baseline and branch work is partial; migration release evidence is not complete. SQLite exists only for local smoke tests and does not replace PostgreSQL as the canonical deployment database.

## Authentication and deployment boundary

The API is local-first. If a token is configured, API requests require:

```http
Authorization: Bearer <SION_LOCAL_API_TOKEN>
```

A non-loopback host requires `SION_LOCAL_API_TOKEN`; startup fails without it. This local bearer boundary is partial and is not production-grade identity or authorization. Public deployment remains unapproved. The API is not evidence of completed document extraction, GraphRAG, or CAD/BIM support; see the status matrix in [../../docs/STATUS.md](../../docs/STATUS.md).

## Verification

Use [../../docs/STATUS.md](../../docs/STATUS.md#verification-baseline) as the single source for commands and the current test baseline (357 tests, 0 failures, some environment-dependent skips). That count is a recorded local observation; do not duplicate or dynamically generate it here.
