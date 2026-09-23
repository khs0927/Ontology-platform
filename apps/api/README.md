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
