# Ontology Platform architecture v0.1

## Canonical layers

1. **Ontology contract** — LinkML + SHACL.
2. **Knowledge truth store** — PostgreSQL entity/relation/evidence tables.
3. **Vector projection** — pgvector-compatible embedding store.
4. **Graph projection** — Apache AGE, rebuildable from canonical tables.
5. **Artifact lake** — Google Drive, addressed by provider id + SHA-256.
6. **Ingestion** — documents first; CAD/BIM/CAIR through optional adapters.
7. **GraphRAG** — LightRAG/LlamaIndex-compatible service boundary.
8. **Presentation** — Ontology Map through API, not hard-coded JSON.

## Invariants

- No relation is accepted without typed source/target and relation_type.
- AI-extracted claims default to unverified.
- Evidence records preserve source locator and extraction method.
- Graph/vector indexes are derived and rebuildable.
- Google Drive stores artifacts and backups, not live runtime databases.
- AEC/CAIR is an optional extension; the domain-neutral core must run without it.

## Implementation order

P1 schema + sync
P2 minimal FastAPI CRUD/query
P3 PostgreSQL runtime
P4 Drive ArtifactStore metadata adapter
P5 map migration/API bridge
P6 document ingestion + evidence
P7 GraphRAG
P8 AGE projection
P9 CAIR/AEC adapter
P10 CAD/BIM ingestion


## Artifact graph identity

Artifact storage metadata may optionally link to a canonical graph entity through `artifacts.entity_id`.

- `Artifact`, `Dataset`, and `Deliverable` entity types may back an artifact record.
- Existing standalone artifact metadata remains valid for backward compatibility.
- A linked graph entity has at most one artifact metadata row.
- Deleting a linked graph entity cascades to its artifact metadata; external provider objects are not automatically deleted.
