# Sion Ontology Platform — Status

Updated: 2026-09-23 (Asia/Seoul)

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
- Python unit/integration suite: 54 passing with all extras (2026-10-08)
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
The API intentionally remains local-only. POST endpoints do not yet have
write authentication, so it must not be exposed publicly until an auth layer
is added.

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

## Upgrade 2026-10-08

- DXF parser now groups by group code 0 instead of raw text splitting, so
  layer `0` values no longer break entities; LWPOLYLINE closed flag is read as a bitmask.
- `POST /api/v1/ingest/ifc` exposes IFC ingestion (IfcOpenShell optional, STEP fallback).
- `POST /api/v1/ingest/documents` rejects non-list or missing paths with 422.
- AGE Cypher builder sanitizes labels and escapes literals (`\`, `'`, `$$`).
- New tests: IFC fallback scanner, DXF layer-0 regression, ingest routes,
  AGE sanitization, non-destructive mounted-Drive publish.

## OSS integration 2026-10-08

- **ezdxf** (`cad` extra) is used for DXF when installed; ASCII fallback kept and
  now also parses real ezdxf R2013 output.
- **IfcOpenShell** (`ifc` extra) is used for IFC when installed; STEP fallback kept.
- **Google Drive API** (`drive` extra): `upload_with_service_account()` with
  `SION_DRIVE_SERVICE_ACCOUNT` (path to JSON key) + `SION_DRIVE_ROOT_FOLDER_ID`,
  `drive.file` scope, append-only (identical MD5 skipped, changed content
  reported as conflict, never overwritten/deleted). `publish()` prefers the
  API and falls back to the mounted folder.
- **Apache AGE**: migration 005 is idempotent; `rebuild_projection()` verified
  against PostgreSQL 17 + AGE 1.7.0 (2 vertices / 1 edge fixture, rebuilt twice).
  pgvector cosine search re-verified on PostgreSQL 17 + pgvector 0.8.0.
- `run_agent_bridge.py --provider` now includes deepseek / hermes / zcode.
- ruff lint clean; wheel/sdist build and PyInstaller Linux build verified.

### Still blocked
- Structured 31-node / 43-edge map export (not fabricated).
- Live Drive upload needs a real service account + shared folder id.
- Windows `.exe` must be built on Windows (CI builds the Linux binary).
- `/map` page is served from the source tree only; it is not in the wheel.
