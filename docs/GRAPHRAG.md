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
- `POST /api/v1/graphrag/project` (`write:knowledge`) projects the canonical graph
- `POST /api/v1/graphrag/query` (`read:knowledge`) `{"question", "mode": "mix|local|global|hybrid|naive", "top_k"}`

Install with `pip install -e ".[graphrag]"`. Note that importing LightRAG can
install missing provider packages at runtime, so the package is imported only
when the engine starts.

## Verified

- `tests/test_graphrag.py` round-trips on local storage.
- Manually verified with the `session_preload_libraries` setup above (no
  `shared_preload_libraries`) on the same versions, with the same result.
- Manually verified on PostgreSQL 16 + Apache AGE 1.6.0 + pgvector 0.6.0:
  two projections left 2 graph nodes, 1 edge, 2 entity vectors and 3 chunk
  vectors, and a `mix` query returned the door entity with its DWG evidence.
