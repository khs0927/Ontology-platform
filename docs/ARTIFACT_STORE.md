# Artifact Store

## Purpose

Large files do not belong inside the knowledge graph or Git repository. The graph stores metadata and provenance; the object itself lives in an artifact store.

Canonical metadata is stored in PostgreSQL `artifacts`:

- stable_key
- name
- storage_uri
- SHA-256 content_hash
- MIME type
- byte size
- provider
- provider_file_id
- additional properties

## Content-addressed staging

`LocalStageStore` computes SHA-256 and stages an immutable copy under:

```text
<stage-root>/<first-two-hash-chars>/<full-sha256>
```

Repeated uploads of identical bytes converge to the same staged object.

## Google Drive adapter boundary

Google Drive is a provider, not the database.

A Drive implementation should:

1. receive a staged object,
2. upload or deduplicate it,
3. return a stable Drive file id,
4. register the resulting `provider_file_id`, `storage_uri`, SHA-256 and metadata through the API,
5. never place live PostgreSQL/SQLite database files in Drive.

No Google OAuth token, service account file, Doppler secret, or API credential is committed to this repository.

## Evidence link

Evidence can point to an artifact record. This keeps the chain:

```text
Entity / Relation -> Evidence -> Artifact metadata -> Drive object
```

Later document/chunk ingestion will add page, line, CAD handle, IFC GlobalId and chunk locators on top of this same chain.
