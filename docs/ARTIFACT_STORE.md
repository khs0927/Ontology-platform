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

Repeated identical bytes converge to the same staged object.

## rclone Google Drive provider

`RcloneDriveStore` delegates Google OAuth and transfer behavior to the open-source `rclone` executable.

Upload path:

```text
<remote>:<base-path>/<first-two-hash-chars>/<full-sha256>
```

The adapter uses:

- `rclone copyto ... --immutable --checksum`
- `rclone lsjson ... --stat --hash --hash-type SHA-256`

The returned object ID is stored as `provider_file_id`. Size and SHA-256 are checked when the backend exposes them.

rclone configuration is external to this repository. OAuth tokens, Google client secrets, service account files, and rclone config files must never be committed.

## Evidence link

```text
Entity / Relation -> Evidence -> Artifact metadata -> Drive object
```

Later document/chunk ingestion will add page, line, CAD handle, IFC GlobalId and chunk locators on top of this same chain.
