# EmbedHub (`sion_embedhub`)

Multi-model embedding framework. One rule drives the design: **vectors are only comparable inside the
same embedding space (model + dimension)**. Equal dimension does not make two models compatible.

| Module | Role |
| --- | --- |
| `registry` | `ModelSpec` per model: provider, native/allowed dims, modalities, asymmetric flag, batch limit; `space_id()` |
| `keys` | `KeyPool.from_env("NVIDIA_API_KEY")` discovers `NVIDIA_API_KEY`, `_1`, `_2` ... (deduplicated, round-robin, per-key cooldown). Values never logged. Add a key by exporting the next `NVIDIA_API_KEY_N`. An empty pool is valid: `models` listing and local (bge-m3) benchmarks run without a key; the missing key only fails when an NVIDIA model is invoked. |
| `providers` | `Embedder.embed(items, role="passage"|"query", dim=None)`; retries, key rotation, batch halving, L2 normalisation, injectable transport. Batch halving applies only to 5xx/413/transport failures; 4xx auth/validation errors surface immediately. |
| `fusion` | `rrf()` rank fusion across spaces; `agreement()` -> `confirmed` / `partial` / `conflict` / `single_source` |
| `store` | `ddl(spec, dim)` -> one pgvector table per space (`halfvec` above 2000 dims); the HNSW index is emitted only up to the pgvector limit (4000 dims for `halfvec`), above that the column stays and exact search is used |
| `bench` / `cli` | recall@k and MRR per model plus RRF fusion; `python -m sion_embedhub.cli models|probe|bench|bench-drawings` |

## Models probed live (NVIDIA API, 2026-11-06)

| key | model | dims | notes |
| --- | --- | --- | --- |
| `nv-1b` | `nvidia/nemotron-3.5-embed-1b` | 2048 native, 1024/512/256 | asymmetric; **500 for batches > 2** (handled) |
| `nv-8b` | `nvidia/nemotron-3.5-embed-8b` | 4096 native, 2048/1024/512 | asymmetric; same batch limit |
| `nv-3-1b` | `nvidia/nemotron-3-embed-1b` | 2048 fixed | no `input_type`; weakest on the sample set |
| `nv-vl` | `nvidia/llama-nemotron-embed-vl-1b-v2` | 2048, 1024/512 | **text + image in one space**; image data URL accepted |
| `bge-m3` | Ollama local | 1024 | free, offline, 8192 ctx |

Returned **404 on this account** (not usable): `llama-3.2-nv-embedqa-1b-v1`, `nv-embedqa-mistral-7b-v2`,
`embed-qa-4`, `snowflake/arctic-embed-l`, `nvclip`, `llama-3.2-nemoretriever-1b-vlm-embed-v1`.

## Storage limits (pgvector)

`store.ddl()` writes one table per space: `vector(d)` up to 2000 dims, `halfvec(d)` above that. The
HNSW index is only emitted where pgvector can build one - 2000 dims for `vector`, **4000 dims for
`halfvec`**. `nv-8b`'s native 4096d space therefore gets a `halfvec(4096)` column **without** an ANN
index (the DDL carries a comment); search still works as an exact sequential scan, only slower.
For ANN search at 4096d-capable quality, use a matryoshka dimension instead (e.g. `nv-8b` @ 2048d or
1024d), which stays inside the halfvec HNSW limit.

## Using it

```bash
python -m sion_embedhub.cli models
python -m sion_embedhub.cli probe
python -m sion_embedhub.cli bench dataset.jsonl --models nv-1b:1024 nv-vl:1024 bge-m3
```

Dataset lines: `{"type":"doc","id":"d1","text":"..."}` or `"image":"render.png"`, and
`{"type":"query","q":"...","relevant":["d1"]}`.

## Text + image cross-check

Index drawing text with a text space and the rendered sheet with `nv-vl` (images and text share that space).
Search each space separately, fuse with `rrf()`, and use `agreement()` as the confidence signal:
`confirmed` = top-1 matches, `conflict` = no overlap -> human review. Calibrate "probability" only against a
labelled query set; the tiny sample in the first benchmark was saturated and says nothing about real drawings.

## Real-drawing benchmark (2026-11-07)

Corpus: the 9 Korean DXF sheets in `packages/aec/tests/fixtures/drawings_ko` (text extracted with ezdxf, image
rendered with matplotlib), 28 hand-labelled queries (`packages/embedhub/bench/drawing_queries.jsonl`, Korean and a
few English). Rebuild with `python packages/embedhub/bench/build_drawings_dataset.py OUT_DIR`, then
`python -m sion_embedhub.cli bench OUT_DIR/drawings.jsonl --models nv-1b:1024 nv-8b:1024 nv-vl:1024 nv-vl@image:1024 bge-m3`
(`@image` indexes the rendered sheet instead of its text).

One command does both steps:

```bash
python -m sion_embedhub.cli bench-drawings OUT_DIR
```

Default models are `nv-1b:1024` (text-only baseline), `nv-vl:1024` (same model, text side) and
`nv-vl@image:1024` (rendered sheet). Pass `--models` to add `nv-8b:1024` and `bge-m3` as in the table below.
Without `NVIDIA_API_KEY` the command still renders, prints `skipped`, and does not call NVIDIA or write a
results file. `--offline` scores that same render with a fake embedder (CI); those numbers are not NVIDIA
results and are not recorded here. `--results FILE` writes the report only after a live model run.

한 명령으로 재현한다: `python -m sion_embedhub.cli bench-drawings OUT_DIR`.
`NVIDIA_API_KEY`가 없으면 시트만 렌더하고 라이브 호출은 건너뛴다. CI는 `--offline`로 같은 렌더와 채점 경로를
가짜 임베더에 태우며, 그 점수는 NVIDIA 결과가 아니다.

| space | recall@1 | MRR |
| --- | --- | --- |
| nv-1b 1024d (text) | 1.00 | 1.00 |
| nv-8b 1024d (text) | 1.00 | 1.00 |
| nv-vl 1024d (text) | 0.96 | 0.98 |
| bge-m3 (text, local) | 0.89 | 0.94 |
| nv-vl 1024d (**image** of the sheet) | 0.61 | 0.71 |
| RRF of all five | 1.00 | 1.00 |

Reading it honestly: 9 sheets / 28 queries is still small, and the sheets' own text is tiny in the render, so the
image space is the weakest signal. Use **text as the primary index, the image space as the independent check**
(verdict `confirmed` when top-1 agrees, `conflict` -> review). nv-8b did not beat nv-1b, so nv-1b @ 1024d is the
default. Re-run on real project sheets before trusting any threshold.

## Canonical choice

* Text embedding for GraphRAG: **`nv-1b` @ 1024d** - identical to the vectors already stored by `sion_graphrag`
  (`nvidia/nemotron-3.5-embed-1b`, 1024d), so nothing needs re-embedding. Sensitive content: `bge-m3` (local).
* Drawing images: `nv-vl` (separate space, never mixed with the text table).
* ArchOntos `embedding_projection` is `vector(1536)`; none of these models emits 1536, so keep its own embedder
  (zero-padded) and do not share it with the drawing spaces.

## Using it from sion_graphrag

`GraphRagConfig` accepts `SION_GRAPHRAG_EMBED_PROVIDER=embedhub`; `SION_GRAPHRAG_EMBED_MODEL` is then a registry key:

```bash
SION_GRAPHRAG_EMBED_PROVIDER=embedhub
SION_GRAPHRAG_EMBED_MODEL=nv-1b
SION_GRAPHRAG_EMBED_DIM=1024
# keys come from NVIDIA_API_KEY, NVIDIA_API_KEY_1, ... (never from this config)
```

Documents are embedded as `passage`, searches as `query` (`sion_embedhub.lightrag.as_query()`), and LightRAG's table
name uses the real model id so existing `nemotron-3.5-embed-1b` 1024d tables are reused. Verified live against a
LightRAG local-storage workspace (3/3 queries returned the right sheet first). The default stays `openai`.
Note: a workstation whose env still has `SION_GRAPHRAG_EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2`,
`DIM=384`, `STORAGE=local` does **not** match the Postgres projection (1024d NVIDIA); set the block above to use it.

## Data handling

Anything sent to the NVIDIA API leaves the machine. Use it only for content cleared for cloud processing;
bge-m3 (Ollama) keeps data local.
