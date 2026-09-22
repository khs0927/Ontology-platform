# PostgreSQL runtime

PostgreSQL is the canonical runtime database for Ontology Platform. SQLite exists only as a lightweight test/development fallback.

## Requirements

- PostgreSQL
- `psql` client
- pgvector extension available to the PostgreSQL server
- Python dependencies from `pyproject.toml`

No database password or DSN should be committed to Git.

## 1. Create a database

Example only:

```bash
createdb ontology_platform
```

## 2. Apply migrations

Use a standard PostgreSQL DSN for `psql`:

```bash
export ONTOLOGY_PG_DSN='postgresql://USER:PASSWORD@HOST:5432/ontology_platform'
bash scripts/apply_migrations.sh
```

The migration helper applies numbered `.sql` files in order and stops on the first error.

`002_vector.sql` intentionally fails if the server does not provide pgvector. That failure is useful: vector capability should not be silently assumed.

## 3. Configure the API

SQLAlchemy/psycopg URL:

```bash
export ONTOLOGY_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/ontology_platform'
uvicorn ontology_api.main:app --app-dir apps/api
```

## 4. Verify the database

```bash
python scripts/verify_postgres.py
```

The verifier reports only database/server capability metadata. It does not print the connection URL or password.

Expected checks:

- PostgreSQL connection succeeds
- `pgcrypto` is installed
- `vector` is installed
- canonical core tables exist
- seed entity/relation types exist

## 5. API health

```text
GET /health
GET /health/db
```

`/health/db` performs a real `SELECT 1` using the configured SQLAlchemy engine.

## Backup principle

Google Drive must receive logical dumps or exported canonical datasets, not PostgreSQL data-directory files, WAL files, or a live database directory.
