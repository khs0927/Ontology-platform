# Ontology Platform Roadmap

## P1 — Core ontology + validation
Status: baseline established

- LinkML-style canonical schema
- SHACL validation rules
- PostgreSQL core tables
- pgvector-compatible projection boundary
- AGE graph projection contract
- non-destructive cross-device backup design

## P2 — FastAPI CRUD/query
Status: in progress

- entity CRUD
- relation CRUD
- evidence CRUD
- health/status endpoints
- repository abstraction
- API tests

## P3 — PostgreSQL runtime
Status: next

- PostgreSQL local runtime
- migrations applied against a real server
- pgvector extension verification
- logical backup/restore
- local SQLite only as test fallback where useful

## P4 — Google Drive ArtifactStore
Status: planned

- Drive file id + SHA-256 registry
- artifact metadata table integration
- snapshots / exports / recovery layout
- no live database files in Drive

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
