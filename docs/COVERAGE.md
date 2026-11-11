# Test coverage

Coverage is reported by the `Tests` workflow as an **informational** signal.
There is no `--cov-fail-under` gate: a coverage drop does not fail a pull
request. The goal for now is to make the current coverage visible on every
change and to keep a machine-readable `coverage.xml` next to each CI run, so a
threshold can be chosen from real data later.

`pytest-cov` is installed ad hoc in CI and is **not** a declared dependency:
`pyproject.toml` and `uv.lock` are intentionally unchanged.

## Running locally

```bash
# one-time: the package with all extras, plus pytest-cov
python -m pip install -e ".[all,test,dev]"
python -m pip install "pytest-cov==7.1.0"

# the same command the CI coverage job runs
python -m pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html
```

| Output | What it is |
|---|---|
| terminal table | per-file statement coverage with missing line numbers (`term-missing`) |
| `coverage.xml` | Cobertura XML; uploaded as the `coverage-report` CI artifact and consumable by Codecov and similar services |
| `htmlcov/index.html` | browsable HTML report; uploaded (zipped) as part of the same artifact |
| `.coverage` | raw coverage database used to regenerate reports without re-running tests |

To restrict the report to project code (recommended when reading the numbers):

```bash
python -m pytest \
  --cov=apps --cov=packages --cov=ontology \
  --cov-report=term-missing --cov-report=xml --cov-report=html
```

The generated files are build outputs and are not committed (`.gitignore`).

## What the CI job does

`.github/workflows/tests.yml` contains a `coverage` job named **Coverage
report**. It runs on the same triggers as the other jobs (pull request to
`main`, push to `main`, manual dispatch):

1. checks out the repository and sets up Python 3.12;
2. installs the package with all optional extras (`.[all,test,dev]`);
3. installs a pinned `pytest-cov` (ad hoc, not added to `pyproject.toml` or
   `uv.lock`);
4. runs the coverage command above;
5. uploads `coverage.xml` and `htmlcov/` as the `coverage-report` artifact
   (`actions/upload-artifact@v7.0.2`, 14 day retention).

The upload step uses `if: always()`, so the reports are available for
inspection even when the test run fails. The coverage job is allowed to fail
when the tests fail; only the coverage *threshold* is absent.

## Baseline

Filled from the first CI run of the `Coverage report` job. Re-run the job
(`workflow_dispatch` or a new push) and append a row when the number needs
refreshing.

| Run | Date (UTC) | Commit | Total (all measured files) | Project code only | Notes |
|---|---|---|---|---|---|
| First CI run (PR #131, run `43043695798`) | 2026-11-11 | `c582abd` | **81%** (8,799 missed / 47,431 statements) | 78.35% (apps/packages/ontology, tests excluded) | 1,944 passed, 54 skipped, 14 subtests in 197 s; `coverage-report` artifact contains `coverage.xml` (1.8 MB) + `htmlcov/` |

The "total" column is the `TOTAL` row printed by the CI job. The "project code
only" column was derived from the same run's `coverage.xml` by keeping files
under `apps/`, `packages/` and `ontology/` and dropping `tests/` paths; it is
the more meaningful baseline for future trend tracking. Area split of that
project-only number: `apps` 88.18%, `packages` 77.16%, `ontology` 80.99%.

## Caveats

- **Report scope.** The repository has no coverage source configuration (no
  `[tool.coverage.run] source` in `pyproject.toml`, no `.coveragerc`) and the CI
  command uses bare `--cov`. pytest-cov therefore records every module imported
  during the run — pytest itself, the test files and third-party packages
  included — and the `TOTAL` row mixes project code with dependency code. The
  per-file rows for project modules are still accurate; use
  `--cov=apps --cov=packages --cov=ontology` (locally, or as a follow-up CI
  change) to get a project-only total.
- **SQLite only.** The run uses the SQLite backend like the `pytest` job.
  PostgreSQL / pgvector behaviour (migrations, extensions) is verified by
  `verify.yml`, not by this coverage number, so PostgreSQL-specific branches
  can look untested.
- **All extras installed.** `pip install -e ".[all,test,dev]"` makes every
  optional integration importable, but external services (Google Drive,
  MinIO/S3, live embedding servers, a running PostgreSQL) are not exercised, so
  those provider modules report low coverage by design.
- **Single platform.** The coverage job runs on `ubuntu-latest`; Windows-only
  code paths are covered by `pytest-windows` (without coverage measurement).
- **Runtime.** Coverage tracing is slower than a plain run. The job has a
  20 minute timeout (the plain `pytest` job has 15). If it starts timing out,
  raise the timeout or scope `--cov` to project code.
- **CircleCI.** `.circleci/config.yml` mirrors only the plain `pytest` job; the
  `coverage-report` artifact exists on GitHub Actions only.
