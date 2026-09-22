# Ontology Platform Roadmap

## P1 — Core ontology + validation
Status: baseline complete

- LinkML-style canonical schema
- SHACL validation rules
- PostgreSQL core tables
- pgvector-compatible projection boundary
- AGE graph projection contract
- non-destructive cross-device backup design

## P2 — FastAPI CRUD/query
Status: baseline complete

- entity CRUD
- relation CRUD
- evidence CRUD
- health + database health endpoints
- repository abstraction
- canonical ORM aligned with PostgreSQL migrations
- compatibility aliases for earlier API field names

## P3 — PostgreSQL runtime
Status: in progress

- idempotent core type/relation seed migration
- migration application helper
- database/extension verification helper
- API ORM aligned to canonical migration column names
- real PostgreSQL + pgvector validation — tracked in issue #1
- logical backup/restore — pending

## P4 — Google Drive ArtifactStore
Status: in progress

- artifact metadata API
- Drive file id + SHA-256 registry fields
- content-addressed local staging
- provider-neutral ArtifactStore protocol
- rclone Google Drive provider adapter
- real authenticated Drive validation — tracked in issue #2
- snapshots / exports / recovery integration — pending

## P5 — Ontology Map bridge
Status: in progress

- versioned structured import contract
- duplicate/dangling/count validation
- synthetic example clearly separated from production source
- recover real 31-node / 43-relation structured source — tracked in issue #3
- canonical DB import and API-backed graph — pending

## P6 — Document ingestion + evidence
Status: planned

- Docling/MinerU style parsing boundary
- document/chunk/artifact/evidence pipeline
- human/machine verification state

## P7 — GraphRAG
Status: planned

- local/free-first embedding path
- graph + vector retrieval
- provenance-aware answers

## P8 — Apache AGE projection
Status: planned

- rebuildable entity/relation projection
- graph queries without making AGE the canonical truth store

## P9 — AEC/CAIR adapter
Status: planned

- reuse selected components from khs0927/Ontology
- DXF/IFC/GIS/CAIR adapters
- license and regression checks before adoption

## P10 — CAD/BIM ingestion
Status: planned

- DWG -> DXF -> semantic parser
- IFC -> semantic objects
- CAD handles / IFC GlobalId provenance
- DWG/DXF/PDF cross-validation

Current isolated test suite: 12 passing tests.
