# Sion Ontology Platform architecture v0.2

This document describes the current P0 remediation boundary and planned work. It is not a production-release design sign-off. See [STATUS.md](STATUS.md) for the release gate and status matrix.

## Canonical layers

1. **Ontology contract**: LinkML and SHACL. Implemented foundation.
2. **Knowledge truth store**: PostgreSQL entity, relation, artifact, document, chunk, and evidence tables. Persistence is implemented; migration integration remains partial.
3. **Vector projection**: pgvector-compatible embedding storage. Implemented foundation, with release evidence still required.
4. **Graph projection**: Apache AGE is optional and rebuildable; not a current production dependency.
5. **Artifact lake**: content-addressed objects and manifests staged for Google Drive. Drive is not a live runtime database.
6. **Ingestion**: multi-agent bridge and DLP module exist. The complete document extraction/evidence gate remains partial.
7. **Presentation**: local-first FastAPI API and map import. Public deployment is not approved.

## Planned boundaries

- **GraphRAG**: planned LightRAG/LlamaIndex-compatible service boundary. No end-to-end GraphRAG extraction is implemented.
- **CAD/BIM**: planned DXF semantic parsing and IFC/IfcOpenShell ingestion. Asset staging/metadata does not equal semantic extraction.
- **Evidence end to end**: persistence/contracts are implemented, but document parsing, claim extraction, and evidence creation are not complete.
- **Production identity**: local bearer protection is partial, not a replacement for production identity and authorization.

## Current boundary and invariants

- No relation is accepted without typed source, target, and relation type.
- AI-extracted claims default to unverified.
- Evidence records preserve source locator and extraction method when evidence is created.
- Graph/vector indexes are derived and rebuildable.
- Google Drive stores artifacts, logical dumps, manifests, and recovery copies, not live runtime databases.
- Local sync is one-way, non-destructive, checksum-manifest based, and atomic at the local file-replacement boundary.
- DLP scanning is fail-closed for the module's supported payload paths; complete ingestion-gate coverage is still partial.
- AEC/CAIR is optional; the domain-neutral core must run without it.

## Implementation order

P0 remediation: API local bearer boundary, Alembic baseline/branch work, DLP and ingestion-gate work, atomic Drive staging, CI contracts, and release evidence.

P1: finish document ingestion and evidence extraction; complete DLP gate integration.

P2: complete Alembic branch integration and production migration runbook.

P3: authenticated Drive uploader/scheduler and structured map import.

P4: GraphRAG boundary, AGE projection evaluation, CAIR/AEC adapters, and CAD/BIM ingestion.
