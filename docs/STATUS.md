# Sion Ontology Platform — Status

Updated: 2026-11-12 04:00 KST (Asia/Seoul). Re-checked against `origin/main` `d972785` (tag `v0.3.0`).

## Current state (re-checked 2026-11-12 KST)

Base: `main` at `d972785` (merge of [#109](https://github.com/khs0927/Ontology-platform/pull/109), 2026-11-12 03:3x KST), which sits on the [v0.3.0](https://github.com/khs0927/Ontology-platform/releases/tag/v0.3.0) tag line. The previously documented base `e2bffe3` ([#48](https://github.com/khs0927/Ontology-platform/pull/48), 2026-10-08) is **259 commits** behind. History length: 578 commits. Release tag: **[v0.3.0](https://github.com/khs0927/Ontology-platform/releases/tag/v0.3.0)** (2026-11-12), built from the [#129](https://github.com/khs0927/Ontology-platform/pull/129) metadata (version bump, `CHANGELOG.md`, `docs/releases/v0.3.0.md`) after its CI went 17/17 green.

Merge wave on 2026-11-11/12 (KST): [#106](https://github.com/khs0927/Ontology-platform/pull/106) 22:49, #107 22:50, #108 23:00, #112 and #118 23:08, [#128](https://github.com/khs0927/Ontology-platform/pull/128) 23:54, [#115](https://github.com/khs0927/Ontology-platform/pull/115), [#113](https://github.com/khs0927/Ontology-platform/pull/113), [#101](https://github.com/khs0927/Ontology-platform/pull/101) 23:55, then [#120](https://github.com/khs0927/Ontology-platform/pull/120), [#122](https://github.com/khs0927/Ontology-platform/pull/122), [#123](https://github.com/khs0927/Ontology-platform/pull/123) 00:12, [#125](https://github.com/khs0927/Ontology-platform/pull/125), [#129](https://github.com/khs0927/Ontology-platform/pull/129), [#130](https://github.com/khs0927/Ontology-platform/pull/130) 00:18–00:19, [#133](https://github.com/khs0927/Ontology-platform/pull/133) 02:05, [#121](https://github.com/khs0927/Ontology-platform/pull/121), [#126](https://github.com/khs0927/Ontology-platform/pull/126), [#131](https://github.com/khs0927/Ontology-platform/pull/131) 02:07, [#124](https://github.com/khs0927/Ontology-platform/pull/124) 02:08, [#132](https://github.com/khs0927/Ontology-platform/pull/132) 02:09, [#135](https://github.com/khs0927/Ontology-platform/pull/135) 02:5x, [#136](https://github.com/khs0927/Ontology-platform/pull/136) 02:5x and [#109](https://github.com/khs0927/Ontology-platform/pull/109) 03:3x. Every merge was gated on a fully completed, failure-free check run (16–20 checks), and the two conflicted branches (#124, #126) were rebased onto `main` with union conflict resolutions before their final green run.

The standing process for this kind of catch-up work — intake, verify, green-gate merge, release, branch hygiene, and the handoff that keeps this document current — is documented in [`docs/ops/COMPLETION-PLAYBOOK.ko.md`](ops/COMPLETION-PLAYBOOK.ko.md).

### Shape of the tree since 2026-10-08

- **ArchOntos is a pinned dependency.** [#119](https://github.com/khs0927/Ontology-platform/pull/119) (`ae18abd`, 2026-11-10 KST) removed the vendored copy under `packages/regulation`. The pin is `534367c` (ArchOntos #22), recorded in the root `pyproject.toml`, `uv.lock`, and `docs/INTEGRATION_CONTRACTS.md`. Regulation CI checks that pin, the no-re-vendor guard, the Sion rule-evaluator bridge, and packaged migrations. ArchOntos lint, unit tests, image, and Helm run in khs0927/ArchOntos.
- **`packages/aec` was caught up** with the archived Ontology tree ([#110](https://github.com/khs0927/Ontology-platform/pull/110), [#114](https://github.com/khs0927/Ontology-platform/pull/114), [#116](https://github.com/khs0927/Ontology-platform/pull/116), [#117](https://github.com/khs0927/Ontology-platform/pull/117)), including the Google Drive CAD GraphRAG pack (`e9bd7eb`, Ontology #97).
- **Main PC cutover is complete.** The 2026-10-09 `-Apply` had stopped with a Windows PowerShell 5.1 `SyntaxError` before re-registering the `\AEC\` tasks; the fixed script ran the full sequence on 2026-11-12 02:21–02:34 KST (task XML backup → worker drain → pre-switch `pg_dump` → db/api recreated on the same volume `ontology_aec-pgdata` → migrations → venv `venv ok` → task re-registration). A partial-substring bug in the activation check left the 9 tasks `Disabled` right after the switch; it was recovered manually and fixed in [#135](https://github.com/khs0927/Ontology-platform/pull/135). Verification: API and containers healthy, all 9 admin tasks point at `C:\CODE\Ontology-platform\packages\aec`, workers run on the new venv, and the GraphRAG reindex finished with **DONE 197 / FAILED 0** (the 6 historical FAILED communities are gone; the job now runs every 2 hours). The DB backup now also lives on another disk (`C:\AECBackup`, SHA-256 identical to the source), and the 2026-10-04 `aec-db` crash was narrowed to the `drop_caches`-during-checkpoint interaction with no host-level disk/USB/Hyper-V event and no OOM trace — mitigations are in the current source. Details in [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md).
- **All-In-Cad** PR [#17](https://github.com/khs0927/All-In-Cad/pull/17) (`agent/autocad-host-2027`) merged 2026-10-29 KST. [#18](https://github.com/khs0927/All-In-Cad/pull/18)–[#22](https://github.com/khs0927/All-In-Cad/pull/22) are merged. No open All-In-Cad pull requests.
- **zium-onboarding** PR #2 (template test fixes, opened 2026-10-08) merged 2026-11-05 KST; #3–#5 merged after it. No open pull requests remain there.

The 2026-10-08 test-count table and the "15 checks" list below are that day's record.

### CI gate on `main` (workflow names as of 2026-11-11)

Tests: pytest; pytest (windows-latest, all extras); uv.lock check + locked install; Coverage report (informational, no gate — [#131](https://github.com/khs0927/Ontology-platform/pull/131)). Verify: SQLite and API tests; PostgreSQL migration verification (now `psql` through the Postgres service container, no `apt` — [#128](https://github.com/khs0927/Ontology-platform/pull/128)). AEC / CAD: aec_intelligence lint + tests + extensions; switch-to-monorepo parse + argv (Windows PowerShell 5.1 and PowerShell 7); operational stack (PostgreSQL + AGE + pgvector + PostGIS); api/worker image; GOD-CAD (ubuntu-latest, py3.12); GOD-CAD (windows-latest, py3.12). Regulation: ArchOntos pin, guard, bridge, migrations (PostgreSQL). Public security: privacy; dependencies. CircleCI: `ci/circleci: pytest`. The Windows agent-bridge exe build runs when package paths change. Path-filtered workflows (drawing-context headless, hindsight advisory) run only when their files change.

All merges above landed with this set green. #128 removed the `apt`/DNS flake that had reddened every PR's Verify job. ArchOntos Helm render and ArchOntos lint/types run in the ArchOntos repository.

### Open pull requests

None open at 2026-11-12 04:00 KST. The whole 2026-11-11/12 batch landed, including [#109](https://github.com/khs0927/Ontology-platform/pull/109) (NVIDIA Auto Ontology read-only federation) after its branch was rebased onto the current `main` and its 20 checks went green, plus [#135](https://github.com/khs0927/Ontology-platform/pull/135) (the legacy-path activation check that the cutover exposed) and [#136](https://github.com/khs0927/Ontology-platform/pull/136) (the cutover record). The live list is always https://github.com/khs0927/Ontology-platform/pulls.

### Open issues

- [#3](https://github.com/khs0927/Ontology-platform/issues/3) — structured 31-node / 43-relation map import. The edges are loaded as unverified candidates. Approving or rejecting them at `/review` is still the owner's decision. `data/review/sion-map-relation-decisions.json` (#53) records a 36-approve / 7-hold proposal; it does not apply those decisions.
- [#33](https://github.com/khs0927/Ontology-platform/issues/33) — SketchUp / Drive follow-up checklist, including whether dump paths stay in the pinned SketchUp files.
- [#71](https://github.com/khs0927/Ontology-platform/issues/71) — mobile and PC-independent operation: Kordoc link and a safe review/write end-to-end path.
- [#79](https://github.com/khs0927/Ontology-platform/issues/79) — repeatable pipeline for adding another SketchUp model.
- ~~[#80](https://github.com/khs0927/Ontology-platform/issues/80)~~ — feed `/review` approvals into guideline weights. Steps landed in #96–#99; the issue was closed at 2026-11-11 23:13 KST when #126 opened. Auto-approve stays off.

### Remaining owner actions

0. **Top priority (any PC):** rotate the Google AI Studio API key that was committed to HS-CAD `opencode.json` (in public history since 2026-05-21; main now uses an env var via HS-CAD #158), then close HS-CAD secret-scanning alert #1 as revoked. Optionally enable Dependabot + secret scanning on power-cad-mcp, hs-steel-cad, All-In-Cad. See the top of `docs/ops/MAIN-PC-TODO.ko.md`.
0b. ~~HS-CAD PR decisions~~ — dropped 2026-11-03: HS-CAD is retired and power-cad-mcp is the only CAD host bridge (HS-CAD contracts removed). The key rotation in item 0 still applies.
0c. ~~zium-onboarding PR #2~~ — merged 2026-11-05 KST (#3–#5 followed; no open PRs). ~~All-In-Cad~~ — #17–#22 merged, nothing open.
1. `/review` (owner): on 2026-11-11 the live `D:\SionData\sion.db` held **221 pending** candidates — SketchUp definition→class assignments 214 (`source_kind=inferred`) plus 7 held map edges. The other 36 of the 43 map edges are already human-approved, so the older "43 unverified" wording is stale. A further **844 guideline-link candidates** exist in the DB but the review API's `source_kind` filter hides them (docs/code mismatch; decide the policy). Issues #3, #33, #79; #80 closed 2026-11-11. Nothing in this tree auto-approves them.
2. ~~Main PC cutover~~ — **done 2026-11-12** (02:21–02:34 KST `-Apply`, verified 04:00 KST). See the cutover bullet above and [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md).
3. ~~`AutoSync_Code_To_GDrive` stays disabled~~ — **verified 2026-11-12**: the task does not exist on the machine, so the live DB is never copied to Drive; export-on-write to `SION_STORAGE_ROOT` remains the design (the API reported `version 0.3.0` and the export files refresh on every commit).
4. ~~GraphRAG refresh after the runtime switch~~ — **done 2026-11-12**: the reindex finished with **DONE 197 / FAILED 0 / PENDING 0** (the 6 historical FAILED communities are gone) and `AEC-GraphRAG-Refresh` now runs every 2 hours (last run 04:00 KST, exit code 0).
5. **Firewall for ports 18080 / 22217 (owner, admin).** The DB dumps are already copied off the USB disk (`C:\AECBackup`, hash-identical to the source) and the crash investigation is closed, but the firewall step still needs the owner: at 2026-11-12 04:00 KST neither port was listening and no `GrokBot-block-*` rule existed, so there is no LAN exposure right now — run `C:\CODE\_ops\grokbot-firewall.ps1` in an **admin** PowerShell before those containers run again (agents must not bypass UAC).
6. Decide whether dump/`skp_path` local paths stay in the pinned SketchUp data files (issue #33).
7. Bring PC checkouts made before 12:23 KST on 2026-10-08 onto the rewritten history (backup, then `fetch` + `reset --hard origin/main`) or archive them; do not push from them meanwhile.
8. **Remote branches were cleaned up on 2026-11-12.** 32 branches whose tips were fully contained in `main` (no open/draft PR, older than 3 days) were deleted; nothing became unreachable. 53 heads remained afterwards, including 39 branches with commits not in `main` that are kept for an owner decision — the full deleted/kept list with old tips is in [`docs/ops/BRANCH-CLEANUP-2026-11-12.md`](ops/BRANCH-CLEANUP-2026-11-12.md). The 19 branches flagged on 2026-10-08 are part of that kept list (names in the historical "Branch cleanup" section below).

## Current state (re-checked 2026-10-08 22:00 KST) — historical snapshot

Base: `main` at `e2bffe3` (#48), 316 commits. Open PRs: none besides this one. Open issues: #3, #33.

### Tests (measured 2026-10-08)

| Suite | Install | Result |
|---|---|---|
| root (`tests/`) | `.[all,test,dev]` | **265 passed, 3 skipped** (the 3 need `SION_TEST_POSTGRES_URL`) |
| root (`tests/`) | minimal `.[test]` | 239 passed, 29 skipped (optional libs absent) |
| `packages/aec` | | 619 passed, 51 skipped |
| `packages/regulation` | local, no PostgreSQL | 213 passed, 39 skipped (PostgreSQL tests run in CI) |
| `packages/cad/god-cad` | | 27 passed |

### CI on `main` — 15 checks, all green (2026-10-08; the job list has since changed, see the 2026-11-11 section)
GitHub Actions (14): pytest; pytest (windows-latest, all extras); SQLite and API tests; PostgreSQL migration
verification; uv.lock check + locked install (all extras); dependencies; privacy; aec_intelligence lint + tests +
extensions; aec_intelligence operational stack (PostgreSQL + AGE + pgvector + PostGIS); aec_intelligence api/worker
image (monorepo build context); ArchOntos lint, types, tests (PostgreSQL); ArchOntos Helm render; GOD-CAD
(ubuntu-latest, py3.12); GOD-CAD (windows-latest, py3.12). CircleCI (1): `ci/circleci: pytest`.

### History rewrites (both owner-approved; force-pushed)
1. **2026-10-08 03:11 KST — exe purge.** `git filter-repo` removed `bin/sion-agent-bridge.exe` from all history
   (pack 75.7 MiB → 2.6 MiB). The binary lives in Release v0.2.0. Details: "Follow-up 2026-10-08" below.
2. **2026-10-08 12:23 KST — privacy rewrite.** Emails, Google Drive file ids and device names were masked in
   public history. `main` and 29 other branches (30 refs) were force-pushed in the same second (12:23:55 KST).
   Old `main` `217ccd3` → new `54e1921` ("Protect public privacy and local HTTP access", added on top). All 263
   commits of the old `main` are kept with the same subjects and author times; the tree differs only in the 9
   masked files. No commit was dropped.

Consequences:
- Every clone made before 12:23 KST is on the **old history** and has diverged from `origin/main`;
  `git pull --ff-only` fails there. Back up, then `git fetch` + `git reset --hard origin/main`, or re-clone
  (see `docs/ops/MAIN-PC-TODO.ko.md` step 1). **Never push from an old clone or old local branch** — it would
  re-upload the purged exe and the unmasked data. A new-history checkout contains `54e1921`
  (`git merge-base --is-ancestor 54e1921 HEAD`).
- Rewritten commits lost GitHub's "Verified" signature badge.

### Branch cleanup (2026-10-08 22:00 KST)
13 remote branches that were fully contained in `main` (`git merge-base --is-ancestor` true and
`git rev-list --count main..<branch>` = 0, no open PR) were deleted after a backup bundle was made outside the
repository: `ci/windows-pytest`, `claude/gallant-goodall-u0z28w`, `complete-2026-10-08`,
`feat/drive-storage-root`, `feat/sketchup-0914-modeling-assets`, `phase1-exe-releases`, `phase2-packages`,
`phase3-regulation`, `phase4-cad-bim-cair`, `phase5-integration-contracts`,
`pr-aec-binaries`, `pr-docs-shacl`, `relations-pipeline-20261008`.
19 stale branches still have commits not in `main` and were **kept** (owner decision): `claude/project-thread-au08rs`,
`codex/cair-error-boundary-20261003`, `codex/circleci-restore-cutover-20260924`,
`codex/fix-private-auth-openapi-20260924`, `codex/fix-windows-file-uri-test-20260924`,
`codex/p0-remediation-20260924`, `codex/pg-verification-integrity-20260923`,
`codex/restore-github-actions-ci-20260924`, `docs/chatgpt-audit-20261002-1105-e92060`, `docs/ci-os-matrix`,
`feat/aec-cair-federation-20261001`, `feat/gap-fill-upgrades`, `feat/hindsight-advisory-memory-20261001`,
`feat/hindsight-advisory-memory-20261002`, `feat/local-gap-fill-and-upgrades`, `feat/scoped-api-security-20261001`,
`feat/sion-auth-firewall-20261001`, `feat/temporal-relations-20261001`, `test/ci-os-coverage`.

## Sprint 2026-10-08 evening (KST)

Final state re-checked 20:30 KST. Window: merged on/after 14:35 KST (`merged:>=2026-10-08T05:35:00Z`).

### Merged
**Ontology-platform** (all CI green before merge)
- [#37](https://github.com/khs0927/Ontology-platform/pull/37) feat(aec): port read-only bridge fail-closed contract + evidence lifecycle (archived Ontology #86/#90/#91; #86 already contained in #90) — 19:48 KST.
- [#38](https://github.com/khs0927/Ontology-platform/pull/38) feat(aec): port bulk scheduling recovery & ingestion metrics (archived Ontology #80) — workers wait/retry on low RAM or missing source roots; rate/ETA fixed — 19:52 KST.
- [#39](https://github.com/khs0927/Ontology-platform/pull/39) feat(aec/ops): `switch-to-monorepo.ps1` + Korean runbook `packages/aec/docs/SWITCH-TO-MONOREPO.ko.md` — dry-run by default, `-Apply` to change, refuses if the DB volume would change — 19:54 KST.
- [#40](https://github.com/khs0927/Ontology-platform/pull/40) fix(aec): netguard treats fake-IP DNS range `198.18.0.0/15` as non-local (drawing text could reach a remote LLM behind Clash-style proxies); hermetic egress tests — 19:55 KST.
- [#41](https://github.com/khs0927/Ontology-platform/pull/41) docs: evening status + `docs/STATUS.ko.md` — 19:57 KST.

**Bridged repos** (changed in their own repos, not from here)
- power-cad-mcp [#42](https://github.com/khs0927/power-cad-mcp/pull/42) HS steel drafting playbook / standard JSON (19:45), [#40](https://github.com/khs0927/power-cad-mcp/pull/40) README / playbook / install-guide sync (19:53), [#43](https://github.com/khs0927/power-cad-mcp/pull/43) `cad_hs_*` asset tools (10 tools, 65 total; `..` path escape fixed) (20:01).
- hs-steel-cad [#7](https://github.com/khs0927/hs-steel-cad/pull/7) asset registry `hs-steel-asset-registry/1` (819 assets; CRLF hash mismatch on Windows fixed) — 19:57 KST.
- korean-land-mcp [#1](https://github.com/khs0927/korean-land-mcp/pull/1) CI added (typecheck + vitest, 29 tests) — 19:48 KST.
- HS-CAD [#157](https://github.com/khs0927/HS-CAD/pull/157) report PyRx import separately from native readiness — 19:45 KST.
- All-In-Cad: no merge; 96 tests pass; draft #15 (conflicting) commented only. Branch `agent/autocad-host-2027` pushed `edba1f9` (PureWindowsPath test fix, dxf-recorder-ci green) — no PR yet.
- zium-onboarding [#1](https://github.com/khs0927/zium-onboarding/pull/1) merged (`bacdf61`): lockfile resync, lint 0 errors; 11 template test failures remain.

### Closed (not merged)
- [#34](https://github.com/khs0927/Ontology-platform/pull/34), [#35](https://github.com/khs0927/Ontology-platform/pull/35) — closed 19:45 KST, superseded by #36 (Windows pytest); the Ubuntu-only premise is obsolete.

### Known follow-ups (non-blocking)
- Follow-up sprint (sprint2/), merged:
  - [#42](https://github.com/khs0927/Ontology-platform/pull/42) contracts re-pinned to the 2026-10-08 evening heads of the bridged repos; contract tests 58 → 81; new `hs-steel-section-catalog/1` schema (+ asset registry schema).
  - [#44](https://github.com/khs0927/Ontology-platform/pull/44) bulk review API `POST /api/v1/relations/candidates/bulk` + Korean `/review` bulk UI (filters, keyboard shortcuts, display-only 추천 hint; no auto-approve).
  - [#45](https://github.com/khs0927/Ontology-platform/pull/45) test deps: httpx2 for Starlette TestClient; `uv.lock` has no known vulnerabilities.
  - [#46](https://github.com/khs0927/Ontology-platform/pull/46) port of archived Ontology #88 headless drawing-context tests (separator-independent asserts; new workflow `aec-drawing-context-headless.yml` on ubuntu/macos/windows). Ontology #89 became `packages/aec/docs/verification-boundary.md`; #83/#84/#87 skipped (archive-state only).
  - [#47](https://github.com/khs0927/Ontology-platform/pull/47) backup/restore smoke test in `verify.yml` (pg_dump/restore on PG17 + pgvector; row counts, extension versions, no pending migrations); closes issue #1 (`scripts/verify-postgres.sh` covers the check; the `verify_postgres.py` named in the issue never existed).
  - Issue #2 closed as superseded by export-on-write (`docs/STORAGE.md`, `drive_export.py`); `AutoSync_Code_To_GDrive` tracked in #33. Open issues now: #3 (waits on owner `/review` of 31 nodes + 43 relations) and #33.
  - korean-land-mcp [#2](https://github.com/khs0927/korean-land-mcp/pull/2) npm audit findings 20 → 2.
  - HS-CAD [#158](https://github.com/khs0927/HS-CAD/pull/158) Pillow >= 12.3; `opencode.json` now reads `{env:GOOGLE_GENERATIVE_AI_API_KEY}` instead of a committed key.
  - power-cad-mcp [#44](https://github.com/khs0927/power-cad-mcp/pull/44) deterministic `OntologyAskTests` via `FakeTimeProvider` (fixes the flaky Windows timing test).
- Open at 20:30 KST: power-cad-mcp #45 (HS-STEEL skills), #49, #46 (CAD-less asset pipeline + Graph RAG index), #47 (headless DXF recover/ATTRIB/paper space), #48 (`cad_hs_search` / `cad_hs_index_status`).
- HS-CAD PR triage done: 32 closed (already on main), none merged, 34 open with Korean comments; owner decisions listed in `docs/ops/MAIN-PC-TODO.ko.md` (HS-CAD section). xiCAD `mcp==1.28.1` pin breaks on Python 3.13.

### New docs
- [`docs/ops/MAIN-PC-TODO.ko.md`](ops/MAIN-PC-TODO.ko.md) — ordered checklist for the main PC (switch to `packages/aec`, verification, firewall, backups, crash follow-up, `/review`, power-cad-mcp / hs-steel-cad update, Sion local, cleanup), each with command, success criterion and rollback.
- [`docs/guidelines/AGENT-WORKFLOW.ko.md`](guidelines/AGENT-WORKFLOW.ko.md) — agent rules distilled from this week (monorepo vs bridged repos, subtree, porting archived PRs, parallel sprint protocol, public-repo privacy, security defaults, PC ops).

### Remaining owner actions

The live list is **Current state (re-checked 2026-11-11 KST)** at the top of this file. The 2026-10-08 evening list (All-In-Cad still had no pull request; zium-onboarding still had 11 failing template tests; the main-PC switch had not been attempted) is superseded there.

## Completed

### P1 — Core ontology and persistence contract
- LinkML core ontology source
- SHACL validation rules
- PostgreSQL canonical schema
- provenance/evidence model
- current Sion Map inventory preservation: 31 nodes / 43 relations
- non-destructive cross-device backup engine with SHA-256 manifests

### P2 — API foundation
- FastAPI CRUD/query layer
- entity, relation, evidence and graph endpoints
- embedding create + vector similarity search endpoints
- PostgreSQL production target
- SQLite smoke-test fallback
- CORS entry for the current Sion Ontology Map
- no destructive/delete endpoints yet

### Map import safety
- `sion-map-export/v1` contract
- duplicate stable-key rejection
- dangling-edge rejection
- expected node/edge count validation
- idempotent non-destructive import

### Native vector layer
- PostgreSQL 16.15 verified
- pgvector 0.8.6 built from upstream source
- native `vector` storage
- vector dimension integrity checks
- cosine nearest-neighbor query verified
- FastAPI embedding write/search round-trip verified
- model/dimension remains configurable; no paid embedding API is required

### Content-addressed Artifact Lake
- SHA-256-addressed immutable object layout
- duplicate content deduplication
- per-object JSON manifest
- hash/size verification
- canonical Google Drive destination URI generation
- Artifact descriptor maps directly to PostgreSQL metadata
- FastAPI artifact create/list/get routes
- ORM and SQL core table set aligned at 9 tables
- intended Drive layout:
  - `00_SOURCES/objects/sha256/<prefix>/<digest>`
  - `00_SOURCES/manifests/<digest>.json`
- large CAD/BIM/PDF assets can live in Drive while PostgreSQL stores metadata/provenance

### Packaging / portability
- monorepo packages: `sion_api`, `sion_ingestion`, `sion_drive_store`
- fresh virtual environment installs with `pip install -e '.[test]'`
- no `PYTHONPATH` dependency after installation
- generated metadata and caches excluded from Git

### Verification
- Python unit/integration suite: 13 passing (P1/P2 at the time; current numbers: "Current state" at the top)
- real HTTP smoke test completed
- real PostgreSQL migration test completed
- real PostgreSQL + pgvector vector API round-trip completed
- PostgreSQL verified:
  - 9 public core tables before vector extension table
  - 11 entity types
  - 14 relation types
  - pgcrypto enabled
  - pgvector 0.8.6 enabled
- staged Git content passed `git diff --cached --check`
- staged content passed high-confidence secret literal audit

## Current blockers / intentionally deferred

### Exact 43-edge migration
The Sites artifact exposes all 31 labels and the relation count (43), but not
structured source/target endpoints. Sion will not infer or fabricate them.
**Update (relation pipeline, below):** the only structured 31/43 file found is
`sion-map-production.json` (PR #8). It is imported as 43 *unverified candidates*
with provenance and is waiting for human review at `/review`.

### Google Drive automatic scheduler
Superseded by export-on-write (see "Google Drive storage root 2026-10-08" below
and `docs/STORAGE.md`). The live database stays on a local disk. Each committed
write exports a consistent snapshot and the graph to `SION_STORAGE_ROOT`
(Google Drive for desktop folder, or `SION_DRIVE_ROOT`). A Windows Scheduled
Task that copies the live DB is not the current design and should stay disabled.

### Doppler
Doppler CLI is installed in the current remote container, but the container
has no authenticated Doppler token/config. No secrets were read or exposed.

### Apache AGE
AGE remains an optional rebuildable graph projection. It will not be made a
hard dependency until the final PostgreSQL hosting target is selected and
extension support is verified.

### Public deployment
Write authentication is in place (see "Completion 2026-10-08"). Default mode is
still `local-only`; public exposure requires the operator to set
`SION_API_AUTH_MODE=bearer`, real tokens in `SION_API_TOKENS_JSON` (from a
secret manager, never committed), `SION_INGEST_ROOTS`, and TLS at the proxy.
No hosting target has been chosen or deployed.

## Next milestones

Most of the original gap list is done (document/DXF/IFC ingest, `/map` → `/api/v1/graph`, LightRAG boundary, AEC/CAIR adapter, export-on-write Drive storage, 31/43 imported as reviewable candidates). Remaining product work is owner-gated review and PC runtime cutover — see **Sprint 2026-10-08 evening** below and issue #33.

Still open for engineering (non-blocking):
1. Keep bridged-repo contract pins current when power-cad-mcp / hs-steel-cad land new versions.
2. Apache AGE as an optional projection once the production PostgreSQL host is chosen.
3. Public deployment only after real tokens, `SION_INGEST_ROOTS`, and TLS at the proxy.

## Gap fill 2026-10-07

- DeepSeek / Hermes / ZCode readers scan local JSON/JSONL logs.
- Document ingest writes unverified EXTRACTED_FROM claims plus evidence.
- DXF parser ingests TEXT, INSERT, LINE, LWPOLYLINE without ezdxf.
- AGE projection SQL + Cypher builder added. Extension remains optional.
- Mounted Drive publish copies staged artifacts. Live API upload still needs a service account.
- /map serves apps/web/index.html against /api/v1/graph.
- Structured 31/43 map endpoints are still not fabricated.

## Completion 2026-10-08

Historical (PR #22 time; current numbers: "Current state" at the top). Verified in a fresh venv (`pip install -e '.[test]'`, Python 3.13):
**62 passed, 1 skipped** (the skip is the LightRAG test, which needs the
`graphrag` extra). With `pip install -e '.[test,graphrag]'`: **63 passed**.

- Write auth: every POST route (entities, relations, invalidate, evidence,
  artifacts, embeddings, graphrag/project, ingest/*) requires `write:knowledge`;
  reads require `read:knowledge`/`read:aec`. Modes `local-only` (default),
  `bearer`, `local-or-bearer`; constant-time token comparison; env validation.
  Tests cover 401/403 per POST route, remote rejection in local-only, and
  `local-or-bearer` from a non-loopback client.
- Ingestion path confinement via `SION_INGEST_ROOTS`; refused in remote-auth
  modes if unset.
- Document ingest + evidence: tested through the API (evidence rows,
  `unverified`, idempotent re-ingest).
- DXF parser: TEXT/INSERT/LINE/open+closed LWPOLYLINE tested.
- IFC ingestion: new `sion_ingestion.ifc_ingest`, optional `ifcopenshell`
  (`.[ifc]` extra) with STEP-text fallback; `POST /api/v1/ingest/ifc`.
  Only the fallback is exercised by tests; the ifcopenshell path is untested
  here because no real IFC model was provided.
- Drive: `upload_with_service_account` (optional `.[drive]` extra), tested with
  a fake Drive client only. Not run against real Drive (no credential).
- `/map` served and verified to call `/api/v1/graph`.
- GraphRAG boundary and AEC/CAIR adapter: existing tests pass (unchanged).
- CI: GitHub workflows aligned on `actions/checkout@v7.0.1` and
  `actions/setup-python@v7.0.0`. Not executed on GitHub from here.

Follow-up (same day): dependency upgrades and optional OSS parsers
- Upgraded: fastapi 0.141.1→0.142.2, sqlalchemy 2.0.54→2.1.3, uvicorn
  0.53.0→0.54.0, asyncpg 0.31.0→0.32.0, setuptools build req >=75→>=84.
  Already current: pydantic 2.13.5, psycopg 3.3.6, httpx 0.28.1, pytest 9.1.1,
  lightrag-hku 1.5.7, pgvector 0.5.0, actions/checkout v7.0.1,
  actions/setup-python v7.0.0.
- New extras: `dxf` (ezdxf), `ifc` (ifcopenshell 0.9), `drive`
  (google-api-python-client, google-auth), `all`, `dev` (ruff, build).
  DXF text fallback rewritten to handle padded group codes and to scan only
  the ENTITIES section; it now matches ezdxf output on the test drawing.
- Results (at the time): all extras, Py 3.12 and 3.13: 66 passed. Minimal `.[test]`:
  62 passed, 4 skipped (optional libs absent). `ruff check .` clean
  (E701/E702/E402 ignored for existing upstream style). wheel + sdist build OK.
  `scripts/build_exe.py` produces a working Linux binary under Python 3.12;
  the Windows .exe must still be built on Windows (PyInstaller cannot
  cross-compile). `bin/sion-agent-bridge.exe` was not rebuilt.

Still blocked (needs the owner's data/credentials):
1. Structured 31-node/43-edge Map export — not fabricated.
2. Drive live upload — superseded. Export-on-write to `SION_STORAGE_ROOT` is the
   current path; do not register a Scheduled Task that copies the live DB.
3. Doppler — no token on this machine.
4. Apache AGE / production PostgreSQL host — target not selected.
5. Public deployment — needs hosting, real tokens, and TLS.

## Monorepo consolidation 2026-10-08 (KST)

| Phase | PR | Merged (KST) |
|---|---|---|
| 1. agent-bridge exe moved to GitHub Releases + Windows build workflow, v0.2.0 | #23 | 02:04 |
| 2. `packages/` layout, extras `cad/bim/rag/drive/all/dev`, lazy imports, `uv.lock` | #24 | 02:16 |
| 3. ArchOntos → `packages/regulation` (subtree), one PostgreSQL (`public` + `regulation` schemas), outbox, rule evaluator, PostgreSQL CI | #25 | 02:21 |
| 4. Ontology → `packages/aec`, GOD-CAD → `packages/cad/god-cad` (subtrees; binaries excluded), one DXF reader `sion_cad.reader` | #26 | 02:35 |
| 5. Integration contracts for the bridged repos (`docs/INTEGRATION_CONTRACTS.md`, `sion_core.contracts`, 58 contract tests), `land.*` regulation facts from korean-land-mcp, `dxf_census` | this PR | |

Release: <https://github.com/khs0927/Ontology-platform/releases/tag/v0.2.0>.

Bridged (not merged): power-cad-mcp, hs-steel-cad, korean-land-mcp, All-In-Cad, CAD-MCP (HS-CAD retired 2026-11-03).
They have separate runtimes (.NET/AutoCAD, Node), and none of them was modified.

Still needs the owner's decision:
1. Purge the two historical `bin/sion-agent-bridge.exe` blobs (~74 MB of the 73.7 MiB pack) from
   history. This rewrites history and needs a force push, so it was not done. **Done later with approval; see the follow-up below.**
2. Archive the merged source repos (ArchOntos, Ontology, GOD-CAD) and CAD-MCP. Not done. **Done later with approval; see the follow-up below.**
3. Structured 31-node/43-edge map export. Still not fabricated.

## Follow-up 2026-10-08 (KST)

- #19 (API validation matching the PostgreSQL CHECK constraints) was updated with main and merged.
- From the superseded #21: PDF/DOCX ingest (`documents` extra; DOCX also without it), the SHACL
  validation endpoint `GET /api/v1/validation/shacl` (`validation` extra, shapes
  `ontology/validation/sion-core.shacl.ttl` or `SION_SHACL_SHAPES`), and Drive backup-before-replace
  (`.history/<UTC stamp>/`, byte comparison instead of size, never deletes).
- aec `POST /v1/search` now accepts power-cad-mcp's `model` hint and rejects a model other than
  `AEC_EMBEDDING_MODEL` with 422 (previously ignored silently).
- #20 and #21 were closed as superseded (#22–#27 and the follow-up PR).
- History purge (user-approved, force-pushed 03:11 KST): `bin/sion-agent-bridge.exe` was removed from all history with
  `git filter-repo`. Pack size went from 75.7 MiB to 2.6 MiB; v0.2.0 release assets are unchanged.
  A pre-rewrite mirror and an all-refs bundle are kept outside the repository.
- The 25 binary files left out of the Ontology import (`fixtures/simple_house.dwg` and 24
  `global/**/*.parquet` companions) are restored byte-identical in `packages/aec`. The three DWG
  tests are back to their Ontology originals (the "fixture not in the monorepo" guards were removed),
  so `packages/aec` now holds every file of Ontology `master` (d39a56a). ArchOntos, GOD-CAD and
  CAD-MCP are archived read-only; Ontology is archived after this change.

## Google Drive storage root 2026-10-08 (KST)

- `sion_api.drive_export`: storage layout under `SION_STORAGE_ROOT` (or `SION_DRIVE_ROOT` +
  `AEC-INTELLIGENCE/01_PROJECTS/SION-ONTOLOGY`), export-on-write hook (debounced `after_commit`).
  Each export writes a consistent SQLite backup (or `pg_dump`), the whole graph as
  `sion-map-export/v1`, evidence JSONL and `storage-manifest.json`. Also
  `GET /api/v1/storage/status`, `POST /api/v1/storage/export`, and the CLI
  `python -m sion_api.drive_export layout|snapshot|publish-assets`.
- Import CLIs (`sion-relations`, and anything else that uses `relations_cli._session`) export once at the end.
  `scripts/run_agent_bridge.py` writes into the storage root and no longer copies the live DB file.
- `scripts/local_embeddings.py`: a local OpenAI-compatible embeddings endpoint (fastembed), so
  GraphRAG works on SQLite + local LightRAG storage without PostgreSQL or a cloud key.
- The live DB stays on a local disk on purpose. Details: `docs/STORAGE.md`.
- `tests/test_drive_export.py` (11 tests).

## Relation data + relation-construction pipeline 2026-10-08 (KST)

### Where the 31/43 relation data was found
Google Drive, the PC (`C:\code` repos, profile folders, the Drive mount) and git history were
searched. The only file with explicit source/target pairs is `sion-map-production.json`
(31 nodes / 43 relations). It is in Google Drive and on the PC, and it came from PR #8
(merged 2026-09-24 02:55 KST, removed from the repo by `3e35521` at 03:09 KST). Its edges were
written in PR #8; they were not exported from the live Sites page, which needs a login.
Details are in `data/sources/PROVENANCE.md`.

- `data/sources/sion-map-production.json`: byte-identical copy
  (sha256 `24f5c468…dd56f`, CRLF kept, `.gitattributes` `-text`).
- `data/bootstrap/sion-map-export.json`: the faithful `sion-map-export/v1` conversion,
  31 nodes / 43 edges, with per-edge provenance (file, sha256, source edge id) and
  `candidate: true`. The test suite regenerates it and compares.
- Count check against the inventory: 31/43, categories match.
- **The 43 edges are `unverified`.** No edge was added, removed or retyped. `VALIDATES`
  (3 edges) is kept as a new 15th canonical relation type (`migrations/007_relation_type_validates.sql`,
  seed, verify workflow and `scripts/verify-postgres.sh` updated to 15).

### Relation-construction capability
1. **Graph export extractor** (`sion_ingestion.graph_export`): sion/ontology map exports, D3
   nodes/links, vis.js (`from`/`to`, `new vis.DataSet`), cytoscape `elements`, mermaid flowcharts,
   GraphML, and HTML pages (inline JSON/JS literals and mermaid blocks) → `sion-map-export/v1`.
   Duplicates, typed self-loops and dangling endpoints are reported and dropped, never repaired.
   A count mismatch fails the conversion.
2. **Candidate extraction** (`sion_ingestion.relation_extraction`): English/Korean verb rules and
   sentence co-occurrence (≥2 sentences) between *known* entities in documents (txt/md/pdf/docx),
   DXF annotations and IFC spatial structure (`IfcRelAggregates`/`Nests`/`ContainedInSpatialStructure`
   → `PART_OF`). Optional LightRAG knowledge-graph → candidates (`rag` extra). Every proposal is
   stored `unverified` with evidence rows (file, `line:N:start-end` or `ifc:#id`, excerpt hash and
   excerpt). Existing verified relations and already-reviewed candidates are never touched.
3. **Review API** (write routes need `write:knowledge`):
   - `GET /api/v1/relations/candidates?status=pending|approved|rejected|all`
   - `GET /api/v1/relations/candidates/{id}`
   - `POST /api/v1/relations/candidates/{id}/approve` → `human_verified`
   - `POST /api/v1/relations/candidates/{id}/reject` → `rejected`
   - `POST /api/v1/extract/relations`
   - `POST /api/v1/import/graph-export` (supports `dry_run`)
   - `POST /api/v1/graphrag/extract-relations`

   A decision is stored in `properties.review` (reviewer, note, time, previous state) and copied
   to the evidence rows. Nothing is deleted. `/api/v1/graph` hides rejected edges unless
   `include_rejected=true`.
4. **Review UI**: `/review` (Korean; filter, approve/reject with a note, evidence excerpts).
   The `/map` edge-drawing bug (it read `source_entity_id`) was fixed; edges are now styled by
   verification state.
5. **CLI**: `sion-relations convert|import|extract|candidates`.

### Verification (at PR #30; current numbers: "Current state" at the top)
- `.[all,test,dev]`, Python 3.13: **193 passed, 3 skipped** (the 3 skips need `SION_TEST_POSTGRES_URL`).
  Minimal `.[test,dev,documents,validation]`: 172 passed, 24 skipped.
  New `tests/test_relations_pipeline.py`: 23 tests.
- PostgreSQL 17 (local): migration runner applies 001–007 and gives 15 relation types; the second run applies 0.
  `tests/test_unified_postgres.py` 3 passed. CLI import of 31/43 is idempotent, and extract/candidates work.
- `ruff check .` is clean and `uv lock --check` passes.

### Still needs the owner
1. Review the 43 imported candidates at `/review`, approving or rejecting each one. They stay
   `unverified` until a person decides.
2. If the live Sites map has different edges, save it as HTML or JSON and run
   `sion-relations convert <file> --expect-nodes 31 --expect-edges 43`.

## SketchUp modelling knowledge pack 2026-10-08 (KST)

- Read-only dump of `0914_담당미팅.skp` (SketchUp 25.0.634, mm) taken through the PC MCP bridge:
  297 definitions, 619 hierarchy nodes, 49 tags, 130 materials, 3 scenes, 3 styles, 1 section plane
  (`data/sources/sketchup/0914-meeting/`, sha256 in `data/sources/PROVENANCE.md`).
- `docs/sketchup/MODELING-GUIDELINES.ko.md`: 31 Korean guideline sections (workflow, units, CAD
  import, tags, group/component, levels, per-object drawing, materials, scenes, cleanup, QA, MCP
  execution, agent judgement). Facts are labelled [관측], inferences [추론], general rules [권장].
- `sion_ingestion.sketchup_assets` builds `data/bootstrap/sketchup-0914-meeting.json`
  (`sion-map-export/v1`, 1,195 nodes / 4,509 edges, including placements below depth 1). Dump facts are
  `machine_verified`; the 214 definition→class assignments and all guideline links are
  `unverified` candidates for `/review`. Details: `docs/SKETCHUP_KNOWLEDGE.md`.
- `tests/test_sketchup_assets.py`: regeneration, coverage, spot facts, bad references, generic
  converter, sqlite import + evidence + `build_custom_kg`.
- Grouping workflow (same day): `scripts/sketchup/grouping_probe.rb` (read-only) →
  `grouping_probe.json`; `docs/sketchup/GROUPING-WORKFLOW.ko.md` has 11 observed grouping rules
  (Decision) and a 12-step workflow (Workflow steps chained by `DEPENDS_ON`/`RELATED_TO`, linked to
  rules, classes, MCP tools and model evidence). All 619 placements are now in the graph
  (`occ:<pid path>` below depth 1). Export: 1,195 nodes / 4,509 edges.
