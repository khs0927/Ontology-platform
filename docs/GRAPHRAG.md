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

Weights are `1 + confidence` (LightRAG floors a weight at its evidence count).
Projection is an idempotent upsert; to drop stale rows, project into a new
`SION_GRAPHRAG_WORKSPACE`.

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

`SION_GRAPHRAG_STORAGE=local` uses LightRAG's file stores under
`SION_GRAPHRAG_WORKING_DIR` (default `runtime/graphrag`) for machines without
AGE.

## Models

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
- `POST /api/v1/graphrag/project` (`write:knowledge`) projects the canonical graph
- `POST /api/v1/graphrag/query` (`read:knowledge`) `{"question", "mode": "mix|local|global|hybrid|naive", "top_k"}`

Install with `pip install -e ".[graphrag]"`. Note that importing LightRAG can
install missing provider packages at runtime, so the package is imported only
when the engine starts.

## Verified

- `tests/test_graphrag.py` round-trips on local storage.
- Manually verified on PostgreSQL 16 + Apache AGE 1.6.0 + pgvector 0.6.0:
  two projections left 2 graph nodes, 1 edge, 2 entity vectors and 3 chunk
  vectors, and a `mix` query returned the door entity with its DWG evidence.
