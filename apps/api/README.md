# Ontology Platform API

FastAPI service for canonical ontology entities, relations and evidence.

Development fallback uses SQLite, but PostgreSQL is the intended canonical runtime.

Run with the lightweight local fallback:

```bash
uvicorn ontology_api.main:app --app-dir apps/api --reload
```

Run with PostgreSQL:

```bash
export ONTOLOGY_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/ontology_platform'
uvicorn ontology_api.main:app --app-dir apps/api
```

Health endpoints:

- `GET /health` — process/API health
- `GET /health/db` — executes `SELECT 1` against the configured database

See `docs/POSTGRES.md` for migrations and runtime verification.
