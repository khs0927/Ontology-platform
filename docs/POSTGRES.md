# PostgreSQL runtime

PostgreSQL is the canonical runtime database for Ontology Platform. SQLite exists only as a lightweight test/development fallback.

## Fast local runtime with Docker

The repository includes a loopback-only development PostgreSQL using the official pgvector image:

```bash
sh scripts/dev_postgres.sh up
```

This starts PostgreSQL 17 + pgvector 0.8.6 on:

```text
127.0.0.1:5433
database: ontology_platform
user: ontology
```

The development container uses PostgreSQL trust authentication but the port is bound to `127.0.0.1` only. Do not use this configuration for a public or production server.

Commands:

```bash
sh scripts/dev_postgres.sh verify
sh scripts/dev_postgres.sh down
sh scripts/dev_postgres.sh reset   # explicitly removes the local DB volume
```

`up` waits for health, applies all numbered SQL migrations inside the PostgreSQL container, and runs `scripts/verify_postgres.py`.

## External PostgreSQL runtime

For an external server:

```bash
export ONTOLOGY_PG_DSN='postgresql://USER:PASSWORD@HOST:5432/ontology_platform'
bash scripts/apply_migrations.sh

export ONTOLOGY_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/ontology_platform'
python scripts/verify_postgres.py
```

No database password or DSN should be committed to Git.

## API

```bash
export ONTOLOGY_DATABASE_URL='postgresql+psycopg://ontology@127.0.0.1:5433/ontology_platform'
uvicorn ontology_api.main:app --app-dir apps/api
```

Health endpoints:

```text
GET /health
GET /health/db
```

Graph snapshot endpoint:

```text
GET /graph
```

The graph endpoint reads canonical entity/relation tables; it does not depend on Apache AGE and can feed the current map UI before AGE is enabled.

## Verification

`scripts/verify_postgres.py` checks:

- PostgreSQL connection
- pgcrypto
- pgvector
- canonical core tables
- seed entity/relation types

It never prints the configured connection URL or password.

## Backup principle

Google Drive receives logical dumps or exported canonical datasets, not PostgreSQL data-directory files, WAL files, or a live database directory.
