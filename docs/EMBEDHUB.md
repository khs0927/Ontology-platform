# EmbedHub (`sion_embedhub`)

Multi-model embedding framework. One rule drives the design: **vectors are only comparable inside the
same embedding space (model + dimension)**. Equal dimension does not make two models compatible.

| Module | Role |
| --- | --- |
| `registry` | `ModelSpec` per model: provider, native/allowed dims, modalities, asymmetric flag, batch limit; `space_id()` |
| `keys` | `KeyPool.from_env("NVIDIA_API_KEY")` discovers `NVIDIA_API_KEY`, `_1`, `_2` ... (deduplicated, round-robin, per-key cooldown). Values never logged. Add a key by exporting the next `NVIDIA_API_KEY_N`. |
| `providers` | `Embedder.embed(items, role="passage"|"query", dim=None)`; retries, key rotation, batch halving, L2 normalisation, injectable transport |
| `fusion` | `rrf()` rank fusion across spaces; `agreement()` -> `confirmed` / `partial` / `conflict` / `single_source` |
| `store` | `ddl(spec, dim)` -> one pgvector table per space (`halfvec` above 2000 dims) |
| `bench` / `cli` | recall@k and MRR per model plus RRF fusion; `python -m sion_embedhub.cli models|probe|bench` |

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

## Data handling

Anything sent to the NVIDIA API leaves the machine. Use it only for content cleared for cloud processing;
bge-m3 (Ollama) keeps data local.
