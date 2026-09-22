# Structured Ontology Map import

The published map currently exposes enough flattened text to confirm 31 nodes, 43 relations and six category totals, but not enough structured data to reconstruct the exact 43 edges safely.

Therefore the platform does **not** infer missing relations.

## Import contract

The first structured migration uses `ontology-map-export/v1`.

Required sections:

- source
- expected_node_count
- expected_relation_count
- categories
- nodes
- relations

Each node carries:

- stable source id
- label
- canonical entity_type_id
- category_id
- optional properties

Each relation carries:

- stable source id
- source_id
- target_id
- canonical relation_type_id
- optional source_uri / source_locator
- optional properties

## Validation

The contract rejects:

- duplicate category/node/relation ids
- unknown category references
- dangling relation endpoints
- node count mismatch
- relation count mismatch

The production 31/43 map will only be imported after its real structured source is recovered.

`data/bootstrap/map-export.example.json` is deliberately synthetic and must never be treated as the production map source.
