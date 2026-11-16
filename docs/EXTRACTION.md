# Extraction

Everything an extractor produces is a **review candidate**: an `unverified` relation with
`properties.candidate = true` and one evidence row per supporting quote, decided in `/review`.
No extractor writes canonical facts or creates entities.

| Extractor | Endpoint | Cost | What it finds |
|---|---|---|---|
| Rules + co-occurrence (`sion-relation-extractor/v1`) | `POST /api/v1/extract/relations` | free | explicit verb phrases between curated entities (Korean and English), DXF mentions, IFC structure, LightRAG edges |
| Ontology-constrained model (`sion-llm-extractor/v1`) | `POST /api/v1/extract/relations/llm` | model calls | typed relations stated in prose that the rules miss |
| Law cross-references (`sion_api.law_refs`) | automatic on `POST /api/v1/law/articles`; `GET /api/v1/law/articles/{law_id}/{article}/refs` | free | 조문 간 인용 (`법 제80조제1항`, `「주택법」 제15조`, `같은 법`, ranges, 별표) |

## Ontology-constrained model extraction

The model is held to the live ontology. The JSON schema of its reply is generated from the
`entity_types` and `relation_types` tables (`GET /api/v1/extract/llm/schema` shows the exact
schema and prompt), and the request uses strict JSON-schema structured output. Importer-only edge
types (`EXTRACTED_FROM`, `EVIDENCED_BY`, `VERSION_OF`) are not offered.

Each reply then passes four deterministic gates. Whatever fails a gate is listed in `rejected`
with the reason:

1. **Schema**: Pydantic validation against the ontology enums. The model gets one retry with the
   error, after which the chunk is listed in `failed_chunks`.
2. **Grounding**: the evidence must be a verbatim quote from the chunk (whitespace and case
   normalised), and both endpoint names must appear in the chunk.
3. **Resolution**: both endpoints must be curated entities, matched by name or `aliases`. Unknown
   names are returned as `entity_suggestions` (name, the model's claimed type, up to three
   quotes) for a person to create. The extractor never creates entities.
4. **Domain/range**: when a relation type sets `source_type_id` / `target_type_id`, the stored
   entity types must satisfy them. Subtypes count, via `entity_types.parent_type_id`. This is the
   SHACL `sh:class` constraint checked before insert, and `GET /api/v1/validation/shacl` still
   validates the whole graph afterwards.

Confidence starts at 0.5 and rises by 0.05 per additional independent quote, capped at 0.75, so
model-only edges rank below rule-backed ones.

```bash
export SION_EXTRACT_BASE_URL=http://localhost:8000/v1   # any OpenAI-compatible endpoint with json_schema output
export SION_EXTRACT_MODEL=Qwen/Qwen3-32B                # or a hosted model behind a compatible gateway
export SION_EXTRACT_API_KEY=...                         # optional bearer token
export SION_EXTRACT_CHUNK_CHARS=4000                    # optional, per model call
export SION_EXTRACT_MAX_CHUNKS=200                      # optional, per request
curl -X POST localhost:8000/api/v1/extract/relations/llm -H 'content-type: application/json' \
  -d '{"paths": ["/data/docs/pipeline.md"]}'
```

When either setting is unset, the endpoint returns 503 and nothing is called. Documents are read
through the format router (`docs/INGESTION.md`), so HWP and scanned PDFs work when their parsers
are available.

## Law cross-references

Korean statutes cite each other in a small, regular grammar, so the extractor is rule based:
exact, explainable and free. References are stored on `law_articles.refs` as
`"<법령명>:<article_key>"`, which is the same identity the evaluation corpus uses. The extractor
runs on ingest unless the caller supplies `refs`. `POST /api/v1/law/refs/rebuild` backfills
stored rows: by default only rows with no refs, and `?only_empty=false` recomputes every row.

The extractor handles these forms:
- 법 / 영 / 규칙 / 시행령 / 시행규칙 (the same law family)
- 같은 법 / 같은 영 (the law named most recently)
- 이 법 / 이 영
- 「…」 bracketed names, and unbracketed full names of laws already in the store
- lists such as `제11조, 제14조 및 제16조`, where later items inherit the first item's law
- ranges such as `제5조부터 제8조까지`, expanded up to 20 articles
- 별표 N / 별표 N의M
- 항 / 호 / 목 detail, kept on the reference

The article's own heading is not counted as a reference.

`GET …/refs?as_of=` returns outgoing and incoming references, resolved against the versions in
force on that date. A target that is not in the store is listed with `resolved: false`, never
dropped, because absence from the corpus is not evidence that the cited article does not exist.

On the 1,159-article building-law evaluation corpus (`data/eval/law-corpus.v1.jsonl.gz`, PR #143):
- 3,789 article references were found.
- 2,818 of them point at laws inside the corpus, and 2,745 of those (97.4%) resolve to a stored
  article.
- The rest cite articles that were deleted and so are missing from the corpus (for example
  건축법 제63조).
