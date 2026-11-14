# Changelog

All notable user-visible changes to this repository are recorded here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Law-article table in PostgreSQL** — `migrations/008_law_articles.sql` was never applied by
  `sion-migrate`, so `/api/v1/law/*` had no table on a migrated database. It is now in the core
  sequence, and a test fails if a migration file is left out again.

### Added

- **Docker Compose local stack** — `compose.yaml` runs PostgreSQL + pgvector, the core migrations
  and the API (bearer auth, loopback ports, health check); `deploy/api.Dockerfile` builds the API
  image with optional extras. CI starts the stack and smoke-tests it. See `docs/DEPLOY_LOCAL.md`.
- **GraphRAG on real PostgreSQL in CI** — `tests/test_graphrag_postgres.py` runs LightRAG's
  Postgres storages and checks that project workspaces stay separate. Per-project GraphRAG now
  refuses to run while `POSTGRES_WORKSPACE` is set, because that variable merges every workspace.
- **GraphRAG per-project workspaces** — `POST /api/v1/graphrag/project?project_id=` and
  `POST /api/v1/graphrag/query {"project_id"}` use a separate LightRAG workspace per project,
  projected from that project's entities only. Project-restricted callers must name a project on
  their ACL; unrestricted callers keep the shared workspace. See `docs/GRAPHRAG.md`.

### Changed

- **GraphRAG graph backend** — with `SION_GRAPHRAG_STORAGE=postgres`, LightRAG now stores its graph in
  plain tables (`PGTableGraphStorage`) instead of Apache AGE (`PGGraphStorage`). LightRAG 1.5.7 refuses
  the AGE backend on AGE 1.8.0+. Existing deployments keep their data by running
  `python -m lightrag.tools.migrate_graph_storage --apply` once, or rebuild with
  `POST /api/v1/graphrag/project`; `SION_GRAPHRAG_GRAPH_BACKEND=age` restores the old backend.
  `GET /api/v1/graphrag/status` reports the active `graph_storage`. See `docs/GRAPHRAG.md`.

### Added

- **Remote MCP server** (upgrade phase 5) — `sion-mcp` (new `mcp` extra, official SDK 2.3)
  serves the knowledge core over stateless Streamable HTTP. It speaks both the 2026-07-28
  per-request envelope and the older initialize handshake. Its tools are all read-only:
  ChatGPT-style `search`/`fetch`, `law_search`/`law_article`/`law_refs` with `as_of`, and
  `get_entity`/`neighbors`/`evidence_for` (review candidates hidden unless asked).
  Access uses the API bearer tokens with `read:knowledge`; project-restricted tokens are refused.
  Without bearer mode it serves loopback only. Refused requests get an RFC 9728
  protected-resource metadata challenge. See `docs/MCP_SERVER.md`.

- **Hybrid law search** (upgrade phase 4) — `GET /api/v1/law/search` defaults to `mode=hybrid`.
  Hybrid mode runs BM25 over word tokens plus Hangul bigrams, adds an optional vector channel
  (`SION_LAW_EMBED_MODEL`, an EmbedHub model key) fused by RRF, and applies citation-graph
  expansion over `law_articles.refs`. Every result reports which channels found it.
  On the building-law gold set, recall@10 rises from 0.625 to 0.977 and MRR from 0.422 to
  0.770. `mode=lexical` keeps the previous scorer. See `docs/EVALUATION.md`.

- **Retrieval evaluation** (`sion_eval`, `packages/eval`) — Korean building-law gold set (44 questions)
  over a 1,159-article statute corpus, recall/MRR/nDCG metrics, baseline retrievers and a CLI
  (`python -m sion_eval.cli run`). Baseline: the current law search reaches recall@10 0.625;
  BM25 over Hangul bigrams reaches 0.977. See `docs/EVALUATION.md`.

### Added

- **Ontology-constrained model extraction** — `POST /api/v1/extract/relations/llm` asks any
  OpenAI-compatible model for relations with a JSON schema generated from the live
  `entity_types`/`relation_types`. Replies pass schema (one retry), verbatim-quote grounding,
  curated-entity resolution and domain/range gates, and the survivors are stored as unverified
  review candidates. Unknown names come back as `entity_suggestions`.
  `GET /api/v1/extract/llm/schema` shows the schema and prompt. See `docs/EXTRACTION.md`.
- **Law cross-references** (law-knowledge slice 3) — a rule extractor fills `law_articles.refs`
  on ingest. It handles 법/영/규칙, 같은 법, 「…」, lists, ranges and 별표, and resolves 97.4% of
  in-corpus references on the evaluation corpus. `GET /api/v1/law/articles/{law_id}/{article}/refs`
  returns outgoing and incoming references as of a date, and `POST /api/v1/law/refs/rebuild`
  backfills stored rows.

### Added

- **Document parser router** (`sion_ingestion.parsers`) — picks a backend per file type:
  HWP/HWPX and `.xls` through the kordoc CLI (MIT, first choice when installed), then
  `hwp-hwpx-parser` (new `hwp` extra) or the built-in HWPX reader. Scanned PDFs and images go to
  any OpenAI-compatible vision OCR endpoint such as PaddleOCR-VL (`SION_OCR_BASE_URL`,
  `SION_OCR_MODEL`; page rendering from the new `ocr` extra), else to kordoc's built-in OCR.
  Docling handles PPTX/XLSX/HTML. `SION_PARSER_PREFER=kordoc|docling` makes either parser the
  first choice for PDF/DOCX too. See `docs/INGESTION.md`.

### Changed

- Document ingest skips now say why: an image without an OCR endpoint, or a scanned PDF, names
  the settings that enable OCR instead of `unsupported type` / `OCR is not performed`.
- Built-in DOCX/HWPX readers refuse XML members over 64 MB uncompressed and use defusedxml when
  it is installed.

### Added

- **Durable ingestion jobs** (upgrade phase 6) — with `SION_JOBS=on` (new `jobs` extra, DBOS
  Transact), `POST /api/v1/jobs/ingest` queues one checkpointed workflow per file
  (parse → load → relation candidates). The system database is the existing PostgreSQL or a
  local SQLite file.
  - Finished steps never re-run, and unfinished workflows resume after a crash.
  - Parsing retries transient errors, and unreadable files end as skips.
  - `…/retry` re-runs a failed job from its first failed step.
  - Concurrency is limited per process. `sion-worker` adds worker processes.
  - Tested on SQLite and PostgreSQL 16. See `docs/JOBS.md`.

## [0.3.0] - 2026-11-11

Monorepo consolidation release: regulation, AEC/Ontology and GOD-CAD now ship as one installable
package set, with the review pipeline, GraphRAG/EmbedHub retrieval and the operational tooling
hardened. See [`docs/releases/v0.3.0.md`](docs/releases/v0.3.0.md) for the release-notes draft.

### Added

- **EmbedHub** — pluggable multi-model embedding framework with an NVIDIA endpoint key pool, RRF
  fusion and a real-drawing benchmark; wired into the GraphRAG search path (#106).
- **Law knowledge (slice 1)** — canonical law-article store with `as_of` search (#75).
- **Regulation workspace** — project review storage, source-cited briefings and the MCP router
  bridge (#58); `building-regulation-report/1` schema for the regulation gateway (#54).
- **AEC consolidation phase 1** — Ontology ingest into the Sion graph/evidence store via
  `aec-cair-snapshot/1`, including DXF/IFC ingestion (#110, #102).
- **Read-only operational preflight** — ontology readiness checks with safety tests and no writes (#103).
- **SketchUp/BIM assets** — asset index with GraphRAG asset search (#69), `sion-bim-asset/1` cards
  for the 0914 model (#67), modeling playbook and parameterized generators (#68), single-house
  window / fire-access / louver assets (#73), per-object ontology overlay (#60), review candidates
  for classifications and block decisions (#65).
- **Review workflow** — bulk decision API and faster `/review` UI (#44), per-item
  ok/reason/batch_id reporting (#99), rejected-state handling (#97) and review-state filtering (#96).
- **Operational tooling** — one-command switch from the archived Ontology checkout to
  `packages/aec` (#39), in-container `pg_dump`/`docker cp` backup with Drive mirror (#76), bulk
  scheduling recovery (#38), graceful worker drain, and watchdog jobs that survive the midnight
  boundary (#111).
- **Storage** — Google Drive storage root with export-on-write of the live database (#32).
- **Integration contracts** — contracts for the bridged repositories, pinned upstream heads and the
  hs-steel section catalog (#27, #42).

### Changed

- **Repository layout** — restructured into `packages/` with feature extras (`cad`, `bim`, `rag`,
  `drive`, `regulation`, `documents`, `validation`) and a single `uv.lock` (#24); ArchOntos merged
  into `packages/regulation` (#25), Ontology into `packages/aec` and GOD-CAD into
  `packages/cad/god-cad` (#26).
- **ArchOntos is a pinned dependency** instead of a vendored copy (#119); `packages/aec` synced with
  Ontology master through Ontology #105/#106 (#114, #116, #117).
- **HS-CAD retired** — remaining PR #100 changes were integrated on top of #102; no new HS-CAD
  contracts are accepted (#105, #102).
- **Review weights** — approval weight boost capped and projection/weights filtered by review
  state (#98, #96); `/review` queues only inferred relations by default (#66).
- **Windows support** — full pytest suite on `windows-latest` (#36), PowerShell 5.1 compatibility
  fixes for operational scripts (#55, #50), and guideline docs kept byte-identical on Windows
  checkouts (#36).
- `apps/api` is now versioned from a single `__version__`, exposed by the API health endpoint.

### Fixed

- Regulation: land-layer failures and schema-validation failures now fail closed (#118).
- GraphRAG: audit previews no longer leak into the live search index (#107).
- SketchUp: invalid namespace scaffolding is rolled back on preflight failure (#108); evidence
  import is idempotent across checkout paths (#94).
- netguard: the fake-IP DNS range (`198.18.0.0/15`) is treated as non-local, with hermetic egress
  tests (#40).
- Review/API/storage hardening batch: atomic review decisions with CAS versions, project ACL
  unification, bounded request input, immutable snapshot SQLite reads, and contract input
  validation (#102, #50).
- AEC ops: watchdog tasks no longer stop at midnight (#111); `switch-to-monorepo` retries and
  PowerShell 5.1 quoting are fixed (#55, #39).

### CI and tooling

- `verify.yml` runs PostgreSQL migration checks inside the service container, removing the
  runner-side apt/DNS dependency (#128).
- Phase-2 read-only upstream drift inventory runs on PRs (#112).
- PostgreSQL 16 client pinned for CI and backups; logical backup/restore smoke test added (#47).
- Dependency security bumps: Pillow, pypdf, pyasn1, certifi, setuptools (`pip-audit` findings).
- `ruff` import-sort/format and `mypy` gates kept green across the tree (#50, #45).

### Documentation

- Regulation framework and the read-first development guidelines (#59); drawing-analysis guide (#52).
- SketchUp/BIM asset playbooks (#68, #82), MCP coexistence guideline (#89), zium template guides
  (#86, #88, #93, #95), AEC 4-stage pipeline and rebuild guides (#83, #84).
- Operational status/runbooks refreshed (status, to-do, switch and backup notes; #41, #43, #48,
  #49, #56, #77).

### Security and privacy

- Public-content privacy checker hardened: `USER` placeholders for example paths, runtime-path
  allowlist, backtick false-positive fix, and public Drive-mirror ID allowlist; local HTTP access
  controls covered by tests.
- No secrets, personal emails, profile paths or private Drive identifiers are included in public
  content (enforced by `scripts/check_public_privacy.py`).

## [0.2.0] - 2026-10-08

Baseline release before this changelog was introduced: the agent-bridge executable moved to GitHub
Releases with a Windows build workflow (#23). Earlier consolidation work is recorded in the
repository history.
