# Durable ingestion jobs

`POST /api/v1/ingest/documents` parses and loads files inside the HTTP request. That is fine for a
few text files, but not for a batch of scanned PDFs that take minutes each to OCR. **Ingestion jobs**
move that work into durable workflows on [DBOS Transact](https://github.com/dbos-inc/dbos-transact-py)
(MIT, `jobs` extra). DBOS is a library, not a server: workflow state lives in a system database,
which is the existing PostgreSQL in production or a local SQLite file in development.

Each file is one workflow (`sion.ingest_file`), made of checkpointed steps:

| Step | Does | On failure |
|---|---|---|
| `parse` | text, extractor and page count through the document parser | retried 3 times (backoff); an unreadable file or a missing parser ends the job as `skipped` with the reason |
| `load` | document and claim nodes plus evidence into the canonical store, all `unverified` | job `ERROR`; `POST …/retry` re-runs from here, reusing the parse output |
| `relations` | rule-based relation candidates for `/review` (skip with `extract_relations: false`) | as above |

A finished step is never run twice. If a worker crashes or restarts, DBOS resumes each unfinished
workflow at its first unfinished step. Every loader keys rows by stable keys, so re-running a step
or re-ingesting a file creates nothing new. Workflows wait in the `sion-ingest` queue, and each
process runs at most `SION_JOBS_CONCURRENCY` (default 2) at a time.

```bash
pip install -e '.[jobs]'
export SION_JOBS=on                   # the API process runs DBOS and the queue
# optional
export SION_JOBS_DATABASE_URL=...     # default: SION_DATABASE_URL when PostgreSQL (DBOS uses its own `dbos` schema),
                                      # else sqlite:///runtime/sion-jobs.sqlite
export SION_JOBS_CONCURRENCY=2
sion-worker                           # extra worker processes on the same system database
```

## API

| Endpoint | Scope | |
|---|---|---|
| `POST /api/v1/jobs/ingest` `{paths, extract_relations}` | write | 202 with one `job_id` per file. Paths are confined to `SION_INGEST_ROOTS`, as for direct ingest |
| `GET /api/v1/jobs?status=` | read | recent jobs in the queue |
| `GET /api/v1/jobs/{id}` | read | status (`ENQUEUED`, `PENDING`, `SUCCESS`, `ERROR`, `CANCELLED`), steps, result or error |
| `POST /api/v1/jobs/{id}/cancel` | write | stop a queued or running job |
| `POST /api/v1/jobs/{id}/resume` | write | continue a cancelled job |
| `POST /api/v1/jobs/{id}/retry` | write | re-run a failed job from its first failed step, as a new job |

Without `SION_JOBS=on` these routes return 503. The synchronous `/api/v1/ingest/documents` is
unchanged.

The tests run on SQLite by default. `SION_TEST_JOBS_POSTGRES_URL=postgresql+psycopg://…` runs the
same tests with PostgreSQL as both the application and the DBOS system database.
