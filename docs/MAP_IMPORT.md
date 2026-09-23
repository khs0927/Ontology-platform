# Structured Ontology Map import

The published map currently exposes enough flattened text to confirm 31 nodes, 43 relations and six category totals, but not enough structured data to reconstruct the exact 43 edges safely.

Therefore the platform does **not** infer missing relations.

## Export contract

`ontology-map-export/v1` contains:

- namespace — stable namespace used to avoid collisions with future maps
- source — human-readable source description
- source_uri — durable source locator used for provenance
- expected node/relation counts
- categories
- nodes
- relations

Every node must specify its canonical `entity_type_id` and `category_id`.
Every relation must specify exact source/target ids and a canonical `relation_type_id`.

## Validation

The contract rejects:

- duplicate category/node/relation ids
- unknown category references
- dangling relation endpoints
- node count mismatch
- relation count mismatch

## Dry-run canonical plan

Before any database write:

```bash
python scripts/plan_map_import.py path/to/export.json > import-plan.json
```

The plan produces deterministic stable keys:

```text
map:<namespace>:node:<source-node-id>
map:<namespace>:relation:<source-relation-id>
```

It also creates one provenance record per relation using the relation-level source URI when present, otherwise the export-level source URI.

Imported relations default to:

```text
source_kind = imported
verification_state = unverified
```

This intentionally separates "successfully imported" from "human verified".

The production 31/43 map will only be written after the real structured source is recovered. `data/bootstrap/map-export.example.json` remains synthetic and must never be treated as production data.
