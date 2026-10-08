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
**Update (relation pipeline, below):** the only structured 31/43 file found is
`sion-map-production.json` (PR #8). It is imported as 43 *unverified candidates*
with provenance and is waiting for human review at `/review`.

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

Follow-up (same day): dependency upgrades and optional OSS parsers
- Upgraded: fastapi 0.141.1→0.142.2, sqlalchemy 2.0.54→2.1.3, uvicorn
  0.53.0→0.54.0, asyncpg 0.31.0→0.32.0, setuptools build req >=75→>=84.
  Already current: pydantic 2.13.5, psycopg 3.3.6, httpx 0.28.1, pytest 9.1.1,
  lightrag-hku 1.5.7, pgvector 0.5.0, actions/checkout v7.0.1,
  actions/setup-python v7.0.0.
- New extras: `dxf` (ezdxf), `ifc` (ifcopenshell 0.9), `drive`
  (google-api-python-client, google-auth), `all`, `dev` (ruff, build).
  DXF text fallback rewritten to handle padded group codes and to scan only
  the ENTITIES section; it now matches ezdxf output on the test drawing.
- Results: all extras, Py 3.12 and 3.13: 66 passed. Minimal `.[test]`:
  62 passed, 4 skipped (optional libs absent). `ruff check .` clean
  (E701/E702/E402 ignored for existing upstream style). wheel + sdist build OK.
  `scripts/build_exe.py` produces a working Linux binary under Python 3.12;
  the Windows .exe must still be built on Windows (PyInstaller cannot
  cross-compile). `bin/sion-agent-bridge.exe` was not rebuilt.

Still blocked (needs the owner's data/credentials):
1. Structured 31-node/43-edge Map export — not fabricated.
2. Drive live upload — needs a service-account key + shared folder ID, or the
   one-time Windows Scheduled Task registration.
3. Doppler — no token on this machine.
4. Apache AGE / production PostgreSQL host — target not selected.
5. Public deployment — needs hosting, real tokens, and TLS.

## Monorepo consolidation 2026-10-08 (KST)

| Phase | PR | Merged (KST) |
|---|---|---|
| 1. agent-bridge exe moved to GitHub Releases + Windows build workflow, v0.2.0 | #23 | 02:04 |
| 2. `packages/` layout, extras `cad/bim/rag/drive/all/dev`, lazy imports, `uv.lock` | #24 | 02:16 |
| 3. ArchOntos → `packages/regulation` (subtree), one PostgreSQL (`public` + `regulation` schemas), outbox, rule evaluator, PostgreSQL CI | #25 | 02:21 |
| 4. Ontology → `packages/aec`, GOD-CAD → `packages/cad/god-cad` (subtrees; binaries excluded), one DXF reader `sion_cad.reader` | #26 | 02:35 |
| 5. Integration contracts for the bridged repos (`docs/INTEGRATION_CONTRACTS.md`, `sion_core.contracts`, 58 contract tests), `land.*` regulation facts from korean-land-mcp, `dxf_census` | this PR | |

Release: <https://github.com/khs0927/Ontology-platform/releases/tag/v0.2.0>.

Bridged (not merged): power-cad-mcp, hs-steel-cad, korean-land-mcp, HS-CAD, All-In-Cad, CAD-MCP.
They have separate runtimes (.NET/AutoCAD, ZWCAD COM, Node), and none of them was modified.

Still needs the owner's decision:
1. Purge the two historical `bin/sion-agent-bridge.exe` blobs (~74 MB of the 73.7 MiB pack) from
   history. This rewrites history and needs a force push, so it was not done. **Done later with approval; see the follow-up below.**
2. Archive the merged source repos (ArchOntos, Ontology, GOD-CAD) and CAD-MCP. Not done. **Done later with approval; see the follow-up below.**
3. Structured 31-node/43-edge map export. Still not fabricated.

## Follow-up 2026-10-08 (KST)

- #19 (API validation matching the PostgreSQL CHECK constraints) was updated with main and merged.
- From the superseded #21: PDF/DOCX ingest (`documents` extra; DOCX also without it), the SHACL
  validation endpoint `GET /api/v1/validation/shacl` (`validation` extra, shapes
  `ontology/validation/sion-core.shacl.ttl` or `SION_SHACL_SHAPES`), and Drive backup-before-replace
  (`.history/<UTC stamp>/`, byte comparison instead of size, never deletes).
- aec `POST /v1/search` now accepts power-cad-mcp's `model` hint and rejects a model other than
  `AEC_EMBEDDING_MODEL` with 422 (previously ignored silently).
- #20 and #21 were closed as superseded (#22–#27 and the follow-up PR).
- History purge (user-approved): `bin/sion-agent-bridge.exe` was removed from all history with
  `git filter-repo`. Pack size went from 75.7 MiB to 2.6 MiB; v0.2.0 release assets are unchanged.
  A pre-rewrite mirror and an all-refs bundle are kept outside the repository.
- The 25 binary files left out of the Ontology import (`fixtures/simple_house.dwg` and 24
  `global/**/*.parquet` companions) are restored byte-identical in `packages/aec`. The three DWG
  tests are back to their Ontology originals (the "fixture not in the monorepo" guards were removed),
  so `packages/aec` now holds every file of Ontology `master` (d39a56a). ArchOntos, GOD-CAD and
  CAD-MCP are archived read-only; Ontology is archived after this change.

## Relation data + relation-construction pipeline 2026-10-08 (KST)

### Where the 31/43 relation data was found
Google Drive, the PC (`C:\code` repos, profile folders, the Drive mount) and git history were
searched. The only file with explicit source/target pairs is `sion-map-production.json`
(31 nodes / 43 relations). It is in Google Drive and on the PC, and it came from PR #8
(merged 2026-09-24 02:55 KST, removed from the repo by `3e35521` at 03:09 KST). Its edges were
written in PR #8; they were not exported from the live Sites page, which needs a login.
Details are in `data/sources/PROVENANCE.md`.

- `data/sources/sion-map-production.json`: byte-identical copy
  (sha256 `24f5c468…dd56f`, CRLF kept, `.gitattributes` `-text`).
- `data/bootstrap/sion-map-export.json`: the faithful `sion-map-export/v1` conversion,
  31 nodes / 43 edges, with per-edge provenance (file, sha256, source edge id) and
  `candidate: true`. The test suite regenerates it and compares.
- Count check against the inventory: 31/43, categories match.
- **The 43 edges are `unverified`.** No edge was added, removed or retyped. `VALIDATES`
  (3 edges) is kept as a new 15th canonical relation type (`migrations/007_relation_type_validates.sql`,
  seed, verify workflow and `scripts/verify-postgres.sh` updated to 15).

### Relation-construction capability
1. **Graph export extractor** (`sion_ingestion.graph_export`): sion/ontology map exports, D3
   nodes/links, vis.js (`from`/`to`, `new vis.DataSet`), cytoscape `elements`, mermaid flowcharts,
   GraphML, and HTML pages (inline JSON/JS literals and mermaid blocks) → `sion-map-export/v1`.
   Duplicates, typed self-loops and dangling endpoints are reported and dropped, never repaired.
   A count mismatch fails the conversion.
2. **Candidate extraction** (`sion_ingestion.relation_extraction`): English/Korean verb rules and
   sentence co-occurrence (≥2 sentences) between *known* entities in documents (txt/md/pdf/docx),
   DXF annotations and IFC spatial structure (`IfcRelAggregates`/`Nests`/`ContainedInSpatialStructure`
   → `PART_OF`). Optional LightRAG knowledge-graph → candidates (`rag` extra). Every proposal is
   stored `unverified` with evidence rows (file, `line:N:start-end` or `ifc:#id`, excerpt hash and
   excerpt). Existing verified relations and already-reviewed candidates are never touched.
3. **Review API** (write routes need `write:knowledge`):
   - `GET /api/v1/relations/candidates?status=pending|approved|rejected|all`
   - `GET /api/v1/relations/candidates/{id}`
   - `POST /api/v1/relations/candidates/{id}/approve` → `human_verified`
   - `POST /api/v1/relations/candidates/{id}/reject` → `rejected`
   - `POST /api/v1/extract/relations`
   - `POST /api/v1/import/graph-export` (supports `dry_run`)
   - `POST /api/v1/graphrag/extract-relations`

   A decision is stored in `properties.review` (reviewer, note, time, previous state) and copied
   to the evidence rows. Nothing is deleted. `/api/v1/graph` hides rejected edges unless
   `include_rejected=true`.
4. **Review UI**: `/review` (Korean; filter, approve/reject with a note, evidence excerpts).
   The `/map` edge-drawing bug (it read `source_entity_id`) was fixed; edges are now styled by
   verification state.
5. **CLI**: `sion-relations convert|import|extract|candidates`.

### Verification
- `.[all,test,dev]`, Python 3.13: **193 passed, 3 skipped** (the 3 skips need `SION_TEST_POSTGRES_URL`).
  Minimal `.[test,dev,documents,validation]`: 172 passed, 24 skipped.
  New `tests/test_relations_pipeline.py`: 23 tests.
- PostgreSQL 17 (local): migration runner applies 001–007 and gives 15 relation types; the second run applies 0.
  `tests/test_unified_postgres.py` 3 passed. CLI import of 31/43 is idempotent, and extract/candidates work.
- `ruff check .` is clean and `uv lock --check` passes.

### Still needs the owner
1. Review the 43 imported candidates at `/review`, approving or rejecting each one. They stay
   `unverified` until a person decides.
2. If the live Sites map has different edges, save it as HTML or JSON and run
   `sion-relations convert <file> --expect-nodes 31 --expect-edges 43`.

## SketchUp modelling knowledge pack 2026-10-08 (KST)

- Read-only dump of `0914_담당미팅.skp` (SketchUp 25.0.634, mm) taken through the PC MCP bridge:
  297 definitions, 619 hierarchy nodes, 49 tags, 130 materials, 3 scenes, 3 styles, 1 section plane
  (`data/sources/sketchup/0914-meeting/`, sha256 in `data/sources/PROVENANCE.md`).
- `docs/sketchup/MODELING-GUIDELINES.ko.md`: 31 Korean guideline sections (workflow, units, CAD
  import, tags, group/component, levels, per-object drawing, materials, scenes, cleanup, QA, MCP
  execution, agent judgement). Facts are labelled [관측], inferences [추론], general rules [권장].
- `sion_ingestion.sketchup_assets` builds `data/bootstrap/sketchup-0914-meeting.json`
  (`sion-map-export/v1`, 1,195 nodes / 4,509 edges, including placements below depth 1). Dump facts are
  `machine_verified`; the 214 definition→class assignments and all guideline links are
  `unverified` candidates for `/review`. Details: `docs/SKETCHUP_KNOWLEDGE.md`.
- `tests/test_sketchup_assets.py`: regeneration, coverage, spot facts, bad references, generic
  converter, sqlite import + evidence + `build_custom_kg`.
- Grouping workflow (same day): `scripts/sketchup/grouping_probe.rb` (read-only) →
  `grouping_probe.json`; `docs/sketchup/GROUPING-WORKFLOW.ko.md` has 11 observed grouping rules
  (Decision) and a 12-step workflow (Workflow steps chained by `DEPENDS_ON`/`RELATED_TO`, linked to
  rules, classes, MCP tools and model evidence). All 619 placements are now in the graph
  (`occ:<pid path>` below depth 1). Export: 1,195 nodes / 4,509 edges.
