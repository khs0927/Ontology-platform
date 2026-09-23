# Continuous integration

## CircleCI baseline

The repository includes `.circleci/config.yml`.

The validation job uses two containers:

1. `cimg/python:3.12` as the primary test executor.
2. `pgvector/pgvector:0.8.6-pg17` as the PostgreSQL service.

The service database is disposable CI-only infrastructure. Its credentials are intentionally fixed test credentials and are not production secrets.

## Validation order

A CI run performs:

1. checkout,
2. PostgreSQL client installation,
3. locked project/development dependency installation with `uv.lock`,
4. database readiness check,
5. all numbered canonical migrations twice to check replay safety,
6. PostgreSQL + pgvector capability verification,
7. the complete pytest suite, including PostgreSQL integration,
8. create a custom-format `pg_dump` archive from the disposable CI database,
9. restore it into a fresh disposable database and compare all modeled table row counts,
10. verify the restored PostgreSQL schema/extensions and rerun PostgreSQL integration tests,
11. publish JUnit results to CircleCI.

The GitHub Actions verification workflow is removed in this change. CircleCI is
the single hosted CI authority after this PR is merged.

Because `ONTOLOGY_TEST_POSTGRES_URL` is configured in CI, `tests/test_postgres_integration.py` runs instead of being skipped.

The ordinary test suite explicitly uses `ONTOLOGY_SECURITY_MODE=disabled`; dedicated security tests still instantiate token mode directly and verify fail-closed behavior.

## Local equivalents

Fast local unit/integration checks without PostgreSQL:

```bash
uv sync --locked --extra dev
uv run pytest -q
```

Local pgvector runtime:

```bash
sh scripts/dev_postgres.sh up
export ONTOLOGY_TEST_POSTGRES_URL='postgresql+psycopg://ontology@127.0.0.1:5433/ontology_platform'
pytest -q
```

## CI status

The repository is connected to CircleCI. The `ci/circleci: test` check has
passed on main and on the private-auth PR. All PostgreSQL and restore checks
run against disposable CI databases; this job must never use production DSNs.

Do not add retries to hide deterministic migration or test failures. The first failing migration/test should remain visible.
