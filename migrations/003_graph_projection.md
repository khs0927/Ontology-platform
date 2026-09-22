# Apache AGE projection

AGE is a projection/query layer, not the canonical source of truth.

Canonical records remain in PostgreSQL `entities` and `relations`.
The AGE graph can be dropped and rebuilt from those tables.

Initial projection rules:

- entity row -> vertex with label = entity_type_id
- relation row -> edge with label = relation_type_id
- stable_key is copied into every vertex/edge
- provenance/evidence remains relational and is joined by stable_key/UUID

This keeps Ontology Platform portable if AGE is unavailable on a specific computer.
