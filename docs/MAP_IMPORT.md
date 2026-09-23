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

## Validation and dry-run

```bash
python scripts/plan_map_import.py path/to/export.json > import-plan.json
```

The contract rejects duplicate IDs, unknown categories, dangling endpoints and node/relation count mismatches.

The dry-run produces deterministic stable keys:

```text
map:<namespace>:node:<source-node-id>
map:<namespace>:relation:<source-relation-id>
```

and one provenance record per relation.

## Transactional API import

Once the structured source has been reviewed:

```text
POST /imports/map
Content-Type: application/json
```

The API:

1. validates the structured contract,
2. checks all referenced canonical entity/relation types,
3. checks that the map stable keys do not already exist,
4. inserts nodes,
5. inserts relations,
6. inserts one provenance Evidence row per relation,
7. commits only after the full map succeeds.

If any step fails, the transaction is rolled back. Re-importing the same namespace currently returns HTTP 409 instead of silently overwriting canonical knowledge.

Imported relations remain `unverified` even when the import itself succeeds. Import success and truth verification are deliberately separate.

## Production 31/43 map

The canonical production map is defined in `data/bootstrap/sion-map-production.json`, matching the 31 visible labels from `data/bootstrap/current-map-inventory.json` across 6 categories with 43 domain relations:

```bash
# Dry-run validation
python scripts/plan_map_import.py data/bootstrap/sion-map-production.json

# Import directly to database
python scripts/import_production_map.py data/bootstrap/sion-map-production.json --db-url <DATABASE_URL>
```

Or via API:
```bash
curl -X POST http://localhost:8000/imports/map \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <WRITE_TOKEN>" \
  -d @data/bootstrap/sion-map-production.json
```

