# Unified database layout

Since the ArchOntos merge (packages/regulation) Sion runs on **one PostgreSQL
database with two schemas**. PostgreSQL stays the canonical truth; vectors,
graph (AGE / LightRAG) and search remain rebuildable projections.

| Schema | Owner | Tables | Migrations | Tracking table |
|---|---|---|---|---|
| `public` | Sion core | `ontology_versions`, `entity_types`, `relation_types`, `entities`, `artifacts`, `documents`, `chunks`, `relations`, `evidence`, `embeddings`, `outbox_events` | `migrations/001_core`, `002_vector`, `004_seed_core_types`, `006_outbox`, `007_relation_type_validates` (+ optional `005_age_projection`) | `public.sion_schema_migrations` |
| `regulation` | ArchOntos | `source_document`, `source_version`, `artifact`, `evidence_span`, `assertion*`, `rule`, `rule_version`, `rule_assertion`, `evaluation`, `decision`, `domain_event`, `outbox_message`, `projection_checkpoint`, `embedding_projection`, `hyperedge*`, `action*`, `audit_log`, ... (29) | `packages/regulation/db/migrations/001..013` | `regulation.schema_migrations` |

The `pgcrypto` and `vector` extensions are installed once in `public`, so
both schemas resolve `gen_random_uuid()` and `vector(n)`.

## Running migrations

```bash
pip install -e '.[regulation]'
python -m sion_api.migrate --dsn postgresql://user:pass@host:5432/sion        # core + regulation
python -m sion_api.migrate --dsn ... --status
python -m sion_api.migrate --dsn ... --skip-regulation                         # core only
python -m sion_api.migrate --dsn ... --with-age                                # + Apache AGE projection
```

- Each file is applied once and SHA-256 checksummed (CRLF-normalised). Editing
  an applied file is an error; add a new migration instead.
- The Sion core files are idempotent, so a database created earlier by
  replaying them with `psql` is adopted without changes.
- ArchOntos migrations are applied by ArchOntos' own runner
  (`archontos.db.migrate`, advisory lock, initdb guard) with
  `search_path = regulation, public`. Standalone:
  `python -m archontos.db.migrate --dsn ... --schema regulation`.

## Running the ArchOntos services against the shared database

```bash
export ARCHONTOS_DATABASE_URL=postgresql+asyncpg://.../sion
export ARCHONTOS_DB_SCHEMA=regulation      # new: connections use search_path regulation,public
```

The least-privilege login (`python -m archontos.db.roles ensure-login`) and
row-level security work per schema exactly as before (migration 012 grants on
`current_schema()`); run those commands with the same search path.

## Transactional outbox

Both halves now use the outbox pattern from ArchOntos ADR-0001:

- **ArchOntos** `regulation.outbox_message`, consumed by its normalization /
  projection workers (unchanged).
- **Sion core** `public.outbox_events` (new). Every session from
  `sion_api.db.build_session_factory` writes an event in the *same flush* as
  the canonical change: `entity.created|updated`, `relation.created|updated|invalidated`,
  `evidence.created`, `artifact.created`. This covers the API and every
  ingestion path (map import, documents, DXF, IFC, agent bridge).
  Consumers pull and acknowledge:
  - `GET /api/v1/outbox?limit=` (read scope) — pending events, oldest first
  - `POST /api/v1/outbox/ack` (write scope) — `{"published":[ids], "failed":[{"id","error"}], "consumer"}`;
    failures get `attempts`, `last_error`, exponential `next_attempt_at` (max 1 h)
  - in-process: `sion_api.outbox.drain(session, handler, consumer=...)`

## Rule evaluation

`POST /api/v1/regulation/evaluate` runs the ArchOntos JSON rule DSL
(`archontos.rules.engine.evaluate_rule`) over request facts and/or a Sion
entity's `properties` (`entity_id`; request facts override, deep merge). It is
fail-closed: a missing fact, an unknown operator or a malformed rule gives
`REVIEW`, never `PASS`/`FAIL`. Sion only evaluates; compiling, approving and
persisting rules stays in the ArchOntos services and their review workflow.
`GET /api/v1/regulation/status` reports whether the `regulation` extra is
installed (otherwise evaluation returns 503).
