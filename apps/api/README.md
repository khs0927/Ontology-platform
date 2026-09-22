# Ontology Platform API

FastAPI service for canonical ontology entities, relations and evidence.

Development fallback uses SQLite, but PostgreSQL is the intended canonical runtime.

Run:

```bash
uvicorn ontology_api.main:app --app-dir apps/api --reload
```

Set PostgreSQL:

```bash
export ONTOLOGY_DATABASE_URL='postgresql+psycopg://user:pass@localhost:5432/ontology'
```
