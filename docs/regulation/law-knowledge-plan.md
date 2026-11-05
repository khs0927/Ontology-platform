# Law-knowledge consolidation plan (2026-10-16)

Goal: one canonical store and API for Korean law articles in Ontology-platform. The four existing
copies become clients of that API instead of each keeping their own corpus or lookup.

## 1. Inventory

| Copy | What it does | Storage | Search | Versioning | Fate |
|---|---|---|---|---|---|
| korean-building-law-monorepo `packages/law-ingest` + `packages/rag` | Collects 법제처 조문단위 JSON, flattens 항/호/목 into one article text (`build_articles.py`); Vector, Keyword and Hybrid (RRF) retrievers; LLM generator | PostgreSQL + pgvector (asyncpg) | vector + tsvector keyword, RRF fusion | none (one text per article) | Move the ingest flattening into the Ontology-platform ingestor. Retire `rag`; the web `/rag` page calls `/api/v1/law/search` |
| korean-law-gpt-actions `lib/permit-review/law-source-resolver.ts` | Calls korean-law-mcp `legal_research` for each evidence item and keeps a 700-character excerpt | none (live call each time); Supabase only stores reviews | delegated to korean-law-mcp | none; `verificationStatus` flag | Resolve against `/api/v1/law/articles/{law}/{article}?as_of=`. Fall back to korean-law-mcp only on a miss |
| building-regulation-gateway `gateway/models.py` Evidence, `mcp_client.py` | Evidence-first report: `snapshot_hash` (sha256), `effective_from/to`, publisher, `source_url`; MCP calls go through an allowlist | SQLite audit | none of its own (upstream MCP) | effective dates on evidence | Keep the audit role. Evidence `snapshot_hash` = article `content_hash`; `document_id` = article id |
| site-pipeline-mcp `knowledge.py`, `lawcheck.py`, `scripts/build_law_kg.py` | In-memory graph of article, rule, fact, zone and source nodes from JSON, with `refers_to`/`cites` edges, token snippets and law versions by 시행일자 | JSON files in the repo | token overlap | per-file 시행일자 | Article nodes are loaded from the API (or a cached export). Rules and calculators stay in site-pipeline |

Also relevant, but not copies: korean-law-mcp (upstream fork) is the live source for 법제처 and stays one.
Ontology-platform already has `documents`/`chunks` and GraphRAG (LightRAG) and ArchOntos
(`packages/regulation`: normalization/legal, projection/search, pgvector).

## 2. Problems the consolidation fixes
- Four answers to "what does 건축법 제61조 say": they differ in text, version and date.
- Only gateway and site-pipeline know about effective dates. The monorepo RAG can return the pre-amendment
  text. The 일조 case (시행령 86조 until 2026-11-11, 개정 건축법 61조 from 2026-11-12) shows the risk.
- No shared citation identity, so evidence from one tool cannot be checked by another.

## 3. Target schema (Ontology-platform, `public` schema)
- `law_articles`: one row per **article version**, unique on (law_id, article_key, effective_from).
  Columns: law_id (법제처 법령ID), law_name, law_kind (act/decree/rule/ordinance/notice), article_key ("61", "61-2"),
  title, text (normalized, 항/호/목 flattened), effective_from, effective_to, promulgated_on, source_url,
  publisher, content_hash (sha256 of title+text), refs (["국토계획법:77", ...]), ingested_at.
  Amendments add rows and nothing is overwritten. The same version with a different hash is rejected (409)
  for human review. **(slice 1, done)**
- `law_article_chunks` (slice 2): article → 항/호 chunks with locator ("②1호"), linked into the existing `chunks`
  table, plus an embedding column in ArchOntos `vector_index`.
- `law_refs` as graph edges (slice 3): REFERS_TO / DELEGATES_TO (위임) relations between article entities, projected
  into GraphRAG/AGE. This replaces site-pipeline `build_law_kg.py` edges.
- `rule → article` CITES edges (slice 4) are owned by ArchOntos rules. site-pipeline rules reference article ids.

## 4. API
| Endpoint | Slice | Notes |
|---|---|---|
| `POST /api/v1/law/articles` (write:knowledge) | 1 ✅ | Bulk ingest of ≤2000 articles. Idempotent; 409 on a changed text under the same version; atomic batch |
| `GET /api/v1/law/search?q=&law=&as_of=&limit=` (read:knowledge) | 1 ✅ | Only versions in force on `as_of` (default today), newest per article; lexical score (title ×3); snippet + citation + content_hash |
| `GET /api/v1/law/articles/{law_id}/{article_key}?as_of=` | 1 ✅ | Accepts `61`, `61-2`, `제61조의2` |
| `search?mode=hybrid` | 2 | pgvector + keyword RRF (port the monorepo `HybridRetriever`) |
| `GET /api/v1/law/articles/{id}/refs` | 3 | graph neighbours |
| `POST /api/v1/law/sync` | 2 | pull from korean-law-mcp / 법제처 OpenAPI by law_id. Needs the 법제처 OC key, so it runs as a job, not in CI |
| MCP tool `law_search` / `law_article` | 3 | exposed through the existing aec-mcp so site-pipeline and gateway agents use it |

Evidence contract: every result carries `law_id`, `article_key`, `effective_from`, `content_hash` and `source_url`.
Those map 1:1 to the gateway `Evidence` (document_id, effective_from, snapshot_hash, source_url), so a gateway report can be
re-verified against the store.

## 5. Migration order
1. **Slice 1 (this PR)**: model, migration 008, ingest/search/lookup endpoints, tests. Offline only.
2. Slice 2: ingest adapter for 법제처 조문단위 JSON (port `render_article`), seed 건축법 / 시행령 / 국토계획법 / 시행령 /
   주차장법 with the 61조 and 86조 versions, chunking + hybrid search.
3. site-pipeline: `knowledge.py` reads articles from the API or an exported JSON snapshot; drop the bundled article JSON.
4. gateway: resolve and verify evidence through `/law/articles`, and record the `content_hash`.
5. gpt-actions: the resolver calls the API first.
6. monorepo: retire `packages/rag` and `law-ingest` once their corpus is ingested.
7. Graph refs + MCP tools.

## 6. Risks / open points
- AGENTS.md puts the regulation initiative on a planning-only hold. This slice is limited to `sion_api` (not ArchOntos
  `packages/regulation`), but the owner should confirm it before merging.
- Ordinances (자치법규) have their own IDs and regional scope; they need `jurisdiction` before slice 2.
- Lexical search on SQLite is O(n) on LIKE matches. That is fine for the curated building corpus (~10^4 articles); hybrid search comes in slice 2.
- 법제처 text licensing: public works, but keep the source_url and publisher on every row.
