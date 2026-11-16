# Changelog

All notable user-visible changes to this repository are recorded here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **GraphRAG graph backend** — with `SION_GRAPHRAG_STORAGE=postgres`, LightRAG now stores its graph in
  plain tables (`PGTableGraphStorage`) instead of Apache AGE (`PGGraphStorage`). LightRAG 1.5.7 refuses
  the AGE backend on AGE 1.8.0+. Existing deployments keep their data by running
  `python -m lightrag.tools.migrate_graph_storage --apply` once, or rebuild with
  `POST /api/v1/graphrag/project`; `SION_GRAPHRAG_GRAPH_BACKEND=age` restores the old backend.
  `GET /api/v1/graphrag/status` reports the active `graph_storage`. See `docs/GRAPHRAG.md`.

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
