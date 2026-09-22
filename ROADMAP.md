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
- API tests
- canonical ORM aligned with PostgreSQL migrations
- compatibility aliases for earlier API field names

Validation: 6 API tests passed before P4; current suite expands this further.

## P3 — PostgreSQL runtime
Status: in progress

- PostgreSQL local runtime
- idempotent core type/relation seed migration
- migration application helper
- database/extension verification helper
- API ORM aligned to canonical migration column names
- migrations applied against a real server — pending
- pgvector extension verification against a real server — pending
- logical backup/restore — pending
- local SQLite remains test fallback only

## P4 — Google Drive ArtifactStore
Status: in progress

- artifact metadata API
- Drive file id + SHA-256 registry fields
- content-addressed local staging
- provider-neutral ArtifactStore protocol
- Google Drive authenticated adapter — pending
- snapshots / exports / recovery integration — pending
- no live database files in Drive

Validation: 8 tests passing with artifact metadata and staging.

## P5 — Ontology Map bridge
Status: planned

- import current 31-node / 43-relation map source
- API-backed graph instead of hard-coded site JSON
- preserve node/category identity
- expose evidence and relation provenance

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
