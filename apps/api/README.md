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


## Write API security

Write operations are protected by default.

Set a bearer token outside Git:

```bash
export ONTOLOGY_SECURITY_MODE=token
export ONTOLOGY_API_TOKEN='replace-with-a-long-random-secret'
```

Clients send:

```text
Authorization: Bearer <ONTOLOGY_API_TOKEN>
```

If token mode is active but no token is configured, write endpoints fail closed with HTTP 503. Missing or invalid credentials return HTTP 401.

Read endpoints such as `GET /graph` remain readable by design. Before any public deployment, place the API behind the existing access layer/reverse proxy as an additional boundary.

For loopback-only development and automated tests, write protection can be disabled explicitly:

```bash
export ONTOLOGY_SECURITY_MODE=disabled
```

Do not use disabled mode on a publicly reachable interface.

Security status can be checked without exposing secrets:

```text
GET /health/security
```

See `docs/SECURITY.md`.
