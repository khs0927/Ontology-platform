# GraphRAG layer (LightRAG)

LightRAG ([HKUDS/LightRAG](https://github.com/HKUDS/LightRAG), MIT, `lightrag-hku==1.5.7`)
is a **rebuildable projection** of the canonical graph, like the AGE projection in
`migrations/003_graph_projection.md`. Canonical rows stay in `entities`, `relations`
and `evidence`; nothing is written back.

## What gets projected

`sion_graphrag.build_custom_kg` turns the canonical tables into a LightRAG custom KG:

- one entity per `entities` row, named by its `stable_key`
- one relationship per relation valid now (`valid_from`/`valid_to`)
- one text chunk per entity and per relation with name, type, description,
  properties, confidence and every evidence `source_uri @ source_locator`

Weights are `1 + confidence` (LightRAG floors a weight at its evidence count),
plus a fixed `+0.25` for `/review`-approved (`human_verified`) relations, capped at
`2.0`. Repeated approval does not raise the weight further.

Review states (Issue #80): `POST /api/v1/graphrag/project` projects approved and
pending relations only. `/review`-rejected relations stay in the database for audit
and are counted with `?include_rejected=true` without writing to LightRAG.
An approval records a person's judgement of a candidate; it is
not a factual verification of the source, and the confidence and evidence of the
relation are never overwritten by it.

Projection is an idempotent upsert; to drop stale rows (for example a relation
projected before it was rejected), project into a new `SION_GRAPHRAG_WORKSPACE`.

### Domain packs

- SketchUp modelling knowledge (`data/bootstrap/sketchup-0914-meeting.json`, Korean guideline
  chunks linked to object classes and to real model objects): see `docs/SKETCHUP_KNOWLEDGE.md`.
  Import with `python -m sion_ingestion.sketchup_assets import --database-url ...`, then project.
  The pack includes the grouping workflow (`sketchup:workflow:grouping`, ordered steps and rules
  from `docs/sketchup/GROUPING-WORKFLOW.ko.md`).

## Storage

`SION_GRAPHRAG_STORAGE=postgres` (default) keeps KV, vectors (pgvector), graph
(Apache AGE) and document status in PostgreSQL. LightRAG reads its own
connection settings: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DATABASE`. The server needs both extensions and
AGE preloaded:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
-- postgresql.conf: shared_preload_libraries = 'age'
```

### Sharing the Ontology pipeline's PostgreSQL

The Ontology pipeline's `aec-postgres-age` container (PostgreSQL 16 with AGE
and pgvector, host port `55432`) can host the projection in a separate
database. `scripts/graphrag_db_setup.sql` creates `sion_graphrag` and loads
AGE per session through `session_preload_libraries`, so the server config
does not change:

```bash
psql -h localhost -p 55432 -U aec -d aec -f scripts/graphrag_db_setup.sql
```

```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=55432
POSTGRES_USER=aec
POSTGRES_PASSWORD=<AEC_DB_PASSWORD>
POSTGRES_DATABASE=sion_graphrag
SION_GRAPHRAG_STORAGE=postgres
SION_GRAPHRAG_WORKSPACE=sion
```

`SION_GRAPHRAG_STORAGE=local` uses LightRAG's file stores under
`SION_GRAPHRAG_WORKING_DIR` (default `runtime/graphrag`) for machines without
AGE.

## Models

No cloud key is needed for embeddings: `scripts/local_embeddings.py` serves an
OpenAI-compatible `/v1/embeddings` on `127.0.0.1` with a multilingual ONNX model (`fastembed`,
`paraphrase-multilingual-MiniLM-L12-v2`, dim 384). Use it with `SION_GRAPHRAG_STORAGE=local`
when PostgreSQL is not running.

Any OpenAI-compatible endpoint works, including local Ollama or vLLM.

| Variable | Required | Meaning |
| --- | --- | --- |
| `SION_GRAPHRAG_EMBED_MODEL` | yes | embedding model name; the layer is off when unset |
| `SION_GRAPHRAG_EMBED_DIM` | yes | embedding dimension |
| `SION_GRAPHRAG_EMBED_BASE_URL` / `_API_KEY` | no | embedding endpoint |
| `SION_GRAPHRAG_LLM_MODEL` | no | enables generated answers; without it queries return retrieved context only |
| `SION_GRAPHRAG_LLM_BASE_URL` / `_API_KEY` | no | LLM endpoint |

## API

- `GET /api/v1/graphrag/status` (`read:knowledge`)
- `POST /api/v1/graphrag/project` (`write:knowledge`) projects the canonical graph and returns `written` counts. With `?include_rejected=true`, it returns `preview` counts and skips indexing and model calls.
- `POST /api/v1/graphrag/query` (`read:knowledge`) `{"question", "mode": "mix|local|global|hybrid|naive", "top_k"}`
- `GET /api/v1/graphrag/assets` (`read:knowledge`) SketchUp BIM asset Graph RAG (see below)

Install with `pip install -e ".[graphrag]"`. Note that importing LightRAG can
install missing provider packages at runtime, so the package is imported only
when the engine starts.

## Review decisions and fact verification (Issue #80)

A `/review` approval records a person's judgement of a candidate relation
(`verification_state = human_verified`). **It does not replace fact verification**: the
relation's confidence and evidence stay as extracted, and the projection only adds a
bounded, idempotent ranking boost. Take numbers and claims from the cited evidence, not
from the fact that a candidate was approved.

- Opposite decisions never overwrite each other: approving a rejected candidate (or the
  reverse) is `409` per item and `conflict` in bulk.
- Re-review goes through `POST /api/v1/relations/candidates/{id}/reopen` with a required
  `note`; the candidate returns to pending and the previous decision (reviewer, note,
  `batch_id`) moves to `properties.review_history`. Candidates are never deleted.
- Every bulk call that applies a decision writes a `review.batch_decided` outbox event
  (aggregate `review_batch`, id = `batch_id`) with the per-id results (`applied`,
  `unchanged`, `conflict`, `not_found`, `not_candidate`, `invalid_id`) in the same transaction.
- `GET /api/v1/review/report` (`read:knowledge`) is the verification report: per state, how many
  relations exist and how many the review-state policy keeps (`projected_under_policy`); a page of
  reviewed relations with weight, reviewer, note, `batch_id` and history; and a page of batches with
  their per-id outcomes. `limit` (1-1000, default 100) and `offset` page relations and batches
  independently (`relations_total`, `batches_total`), and `batch_id` restricts both to one batch.
  Rejected relations are reported as not kept by the policy unless `?include_rejected=true` (audit).
- The live index applies the same default policy: `POST /api/v1/graphrag/project` projects
  verified + unverified relations and leaves rejected ones out. The report sets
  `live_index_applies_policy: true` when its policy is that default; this field does not
  verify an existing index. Rebuild in a fresh workspace if rejected relations were previously indexed.

## SketchUp BIM asset index (`sion-bim-asset-index/1`)

`sion_ingestion.asset_index` turns the SketchUp BIM asset cards (`sion-bim-asset/1`,
`data/assets/sketchup/<model>/cards.jsonl` + `data/assets/sketchup/recipes/*.json`) into one
read-only SQLite file: knowledge graph (`node`/`edge`), FTS5 `unicode61` + `trigram` (Korean
substrings) and float32 vectors. It needs no LightRAG, PostgreSQL or network.

* Graph edges: `instance_of` (instance → definition), `in_class`, `maps_to_ifc`, `uses_material`,
  `on_level`, `made_by` (asset/class → recipe), `contains` (parent → child), `tagged`, `in_model`.
* Embeddings: a local OpenAI-compatible endpoint when `SION_ASSET_EMBED_URL` is set (for example
  text-embeddings-inference serving `BAAI/bge-m3`, model from `SION_ASSET_EMBED_MODEL`); the URL must be
  loopback/private or the build fails. Otherwise the deterministic `hash-chargram-384-v1` embedder is
  used. The model name is stored in `meta` and the query is embedded with the same model.
* Query: BM25 + trigram + vector + Korean/English class lexicon + dimension match (`1.2m`, `450mm`)
  fused with RRF, then 1–2 graph hops (recipe, materials, IFC class, level, definition, children)
  returned as `context`. Parts inside blocks (`inside_block`) are hidden unless asked for.
* Index location: `SION_ASSET_INDEX`, else `$SION_STORAGE_ROOT/SketchUp-Assets/_index/sketchup-assets.sqlite`
  (Google Drive: `G:\내 드라이브\SketchUp-Assets\_index\`), else `data/assets/sketchup/_index/`.
  The SQLite file is derived data and is not committed; `data/assets/sketchup/_index/manifest.json` records counts and hashes.

```
python -m sion_ingestion.asset_index build --manifest data/assets/sketchup/_index/manifest.json
python -m sion_ingestion.asset_index query "유리난간 1.2m" -k 5
curl "http://localhost:8000/api/v1/graphrag/assets?q=카페%20의자&k=5"
```

`GET /api/v1/graphrag/assets?q=&k=&expand=&class=&model=&include_inside_block=` (read scope) answers from the
same file and reloads it when its mtime changes; 503 when the index has not been built.

## Verified

- `tests/test_graphrag.py` round-trips on local storage.
- Manually verified with the `session_preload_libraries` setup above (no
  `shared_preload_libraries`) on the same versions, with the same result.
- Manually verified on PostgreSQL 16 + Apache AGE 1.6.0 + pgvector 0.6.0:
  two projections left 2 graph nodes, 1 edge, 2 entity vectors and 3 chunk
  vectors, and a `mix` query returned the door entity with its DWG evidence.
