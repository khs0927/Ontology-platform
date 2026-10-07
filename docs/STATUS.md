# Sion Ontology Platform — Status

Updated: 2026-10-08 (Asia/Seoul)

## Completed

### P1 — Core ontology and persistence contract
- LinkML core ontology source
- SHACL validation rules
- PostgreSQL canonical schema
- provenance/evidence model
- current Sion Map inventory preservation: 31 nodes / 43 relations
- non-destructive cross-device backup engine with SHA-256 manifests

### P2 — API foundation
- FastAPI CRUD/query layer
- entity, relation, evidence and graph endpoints
- embedding create + vector similarity search endpoints
- PostgreSQL production target
- SQLite smoke-test fallback
- CORS entry for the current Sion Ontology Map
- no destructive/delete endpoints yet

### Map import safety
- `sion-map-export/v1` contract
- duplicate stable-key rejection
- dangling-edge rejection
- expected node/edge count validation
- idempotent non-destructive import

### Native vector layer
- PostgreSQL 16.15 verified
- pgvector 0.8.6 built from upstream source
- native `vector` storage
- vector dimension integrity checks
- cosine nearest-neighbor query verified
- FastAPI embedding write/search round-trip verified
- model/dimension remains configurable; no paid embedding API is required

### Content-addressed Artifact Lake
- SHA-256-addressed immutable object layout
- duplicate content deduplication
- per-object JSON manifest
- hash/size verification
- canonical Google Drive destination URI generation
- Artifact descriptor maps directly to PostgreSQL metadata
- FastAPI artifact create/list/get routes
- ORM and SQL core table set aligned at 9 tables
- intended Drive layout:
  - `00_SOURCES/objects/sha256/<prefix>/<digest>`
  - `00_SOURCES/manifests/<digest>.json`
- large CAD/BIM/PDF assets can live in Drive while PostgreSQL stores metadata/provenance

### Packaging / portability
- monorepo packages: `sion_api`, `sion_ingestion`, `sion_drive_store`
- fresh virtual environment installs with `pip install -e '.[test]'`
- no `PYTHONPATH` dependency after installation
- generated metadata and caches excluded from Git

### Verification
- Python unit/integration suite: 13 passing
- real HTTP smoke test completed
- real PostgreSQL migration test completed
- real PostgreSQL + pgvector vector API round-trip completed
- PostgreSQL verified:
  - 9 public core tables before vector extension table
  - 11 entity types
  - 14 relation types
  - pgcrypto enabled
  - pgvector 0.8.6 enabled
- staged Git content passed `git diff --cached --check`
- staged content passed high-confidence secret literal audit

## Current blockers / intentionally deferred

### Exact 43-edge migration
The Sites artifact exposes all 31 labels and the relation count (43), but not
structured source/target endpoints. Sion will not infer or fabricate them.
The importer is ready for a structured Map export.

### Google Drive automatic scheduler
The Linux @remote runtime can write the Windows-mounted shared directory but
cannot currently invoke Windows PowerShell/CMD. The revised Windows installer
is ready but its Scheduled Task cannot be registered autonomously through the
current connector.

The content-addressed Drive layout and staging layer are implemented. The
remaining step is an authenticated Drive uploader or the one-time Windows
scheduler registration.

### Doppler
Doppler CLI is installed in the current remote container, but the container
has no authenticated Doppler token/config. No secrets were read or exposed.

### Apache AGE
AGE remains an optional rebuildable graph projection. It will not be made a
hard dependency until the final PostgreSQL hosting target is selected and
extension support is verified.

### Public deployment
Write authentication is in place (see "Completion 2026-10-08"). Default mode is
still `local-only`; public exposure requires the operator to set
`SION_API_AUTH_MODE=bearer`, real tokens in `SION_API_TOKENS_JSON` (from a
secret manager, never committed), `SION_INGEST_ROOTS`, and TLS at the proxy.
No hosting target has been chosen or deployed.

## Next milestones

1. Add document ingestion + evidence extraction.
2. Add authenticated Drive uploader/scheduler when a usable credential path exists.
3. Obtain structured 31-node/43-edge map export and import it.
4. Point the frontend graph layer to `/api/v1/graph`.
5. Add LightRAG-compatible GraphRAG boundary.
6. Add AEC/CAIR adapter for selected useful parts of `khs0927/Ontology`.
7. Add CAD DXF semantic parser and IFC/IfcOpenShell ingestion.

## Gap fill 2026-10-07

- DeepSeek / Hermes / ZCode readers scan local JSON/JSONL logs.
- Document ingest writes unverified EXTRACTED_FROM claims plus evidence.
- DXF parser ingests TEXT, INSERT, LINE, LWPOLYLINE without ezdxf.
- AGE projection SQL + Cypher builder added. Extension remains optional.
- Mounted Drive publish copies staged artifacts. Live API upload still needs a service account.
- /map serves apps/web/index.html against /api/v1/graph.
- Structured 31/43 map endpoints are still not fabricated.

## Completion 2026-10-08

Verified in a fresh venv (`pip install -e '.[test]'`, Python 3.13):
**62 passed, 1 skipped** (the skip is the LightRAG test, which needs the
`graphrag` extra). With `pip install -e '.[test,graphrag]'`: **63 passed**.

- Write auth: every POST route (entities, relations, invalidate, evidence,
  artifacts, embeddings, graphrag/project, ingest/*) requires `write:knowledge`;
  reads require `read:knowledge`/`read:aec`. Modes `local-only` (default),
  `bearer`, `local-or-bearer`; constant-time token comparison; env validation.
  Tests cover 401/403 per POST route, remote rejection in local-only, and
  `local-or-bearer` from a non-loopback client.
- Ingestion path confinement via `SION_INGEST_ROOTS`; refused in remote-auth
  modes if unset.
- Document ingest + evidence: tested through the API (evidence rows,
  `unverified`, idempotent re-ingest).
- DXF parser: TEXT/INSERT/LINE/open+closed LWPOLYLINE tested.
- IFC ingestion: new `sion_ingestion.ifc_ingest`, optional `ifcopenshell`
  (`.[ifc]` extra) with STEP-text fallback; `POST /api/v1/ingest/ifc`.
  Only the fallback is exercised by tests; the ifcopenshell path is untested
  here because no real IFC model was provided.
- Drive: `upload_with_service_account` (optional `.[drive]` extra), tested with
  a fake Drive client only. Not run against real Drive (no credential).
- `/map` served and verified to call `/api/v1/graph`.
- GraphRAG boundary and AEC/CAIR adapter: existing tests pass (unchanged).
- CI: GitHub workflows aligned on `actions/checkout@v7.0.1` and
  `actions/setup-python@v7.0.0`. Not executed on GitHub from here.

Still blocked (needs the owner's data/credentials):
1. Structured 31-node/43-edge Map export — not fabricated.
2. Drive live upload — needs a service-account key + shared folder ID, or the
   one-time Windows Scheduled Task registration.
3. Doppler — no token on this machine.
4. Apache AGE / production PostgreSQL host — target not selected.
5. Public deployment — needs hosting, real tokens, and TLS.
