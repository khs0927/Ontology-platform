# packages/aec catch-up with khs0927/Ontology (consolidation phase 2), 2026-11-09

> Plan: [CONSOLIDATION_PLAN.md](CONSOLIDATION_PLAN.md) §4, phase 2. Intentional differences that remain:
> [`packages/aec/UPSTREAM.md`](../packages/aec/UPSTREAM.md).

## 요약 (Korean)

- `packages/aec`는 이제 **khs0927/Ontology `master` @ `8938175`**(`89381756cb9e9fcc90ce0ea2e719a9d53b94ad43`, #104)까지
  반영되었습니다. Ontology `master`를 동결할 기준 커밋이 이것입니다.
- 가져오기 기준(import base)은 Ontology `d39a56a`(#93)입니다. 그 뒤 `master`의 first-parent 커밋 10개를 하나씩 검토했습니다.
  7개는 새로 이식했고, 2개(#94, #96)는 이미 이식되어 있었으며, #100은 대부분 이미 들어와 있어 나머지 문서와 테스트만 추가했습니다.
- 양쪽이 같이 고친 곳은 플랫폼 쪽 최신 변경을 우선했습니다. 예외는 netguard(#99) 하나입니다. 업스트림 쪽이 더 새롭고(10-17)
  더 안전해서(DNS를 전혀 신뢰하지 않음) 업스트림을 택했고, 플랫폼 테스트를 거기에 맞췄습니다.
- `aec-cair-snapshot/1` 계약 출력은 바뀌지 않았습니다. 고정 픽스처와 `upstream_commit`(`d81598f`)은 그대로 둡니다.
- Ontology 저장소는 수정하지 않았습니다(읽기 전용 참조).

## Method

`git subtree pull` cannot work because the import came from a filter-repo copy and the hashes differ. Each upstream
first-parent commit `C` (parent `P`) was replayed as a path-mapped three-way patch:

1. Build two synthetic trees from the platform `HEAD` with `packages/aec/` replaced by Ontology `P` and by Ontology `C`.
   Both drop `.github/`, `docs/CONSOLIDATION_PLAN.md`, `docs/CLOUD_COMPLETION_2026-11-05.md` and `docs/ROLE_IN_ECOSYSTEM.md`
   (Ontology repository metadata; see "Not ported").
2. `git cherry-pick --no-commit -X no-renames` the synthetic `P → C` commit onto the branch. This is a real three-way merge
   with `P` as the base. Platform-only files are untouched, and a hunk the platform already has merges as a no-op.
3. Resolve conflicts (rules below), then commit with an `Upstream-Commit:` trailer.

Conflict rule: where both sides changed the same lines, keep the platform's newer change and add the upstream intent
around it. The exception is when the upstream change is newer and stricter on security (netguard).

Import base: Ontology `d39a56a` (#93, 2026-10-06), as recorded in `docs/STATUS.md` ("`packages/aec` now holds every
file of Ontology `master` (d39a56a)"). A tree comparison confirms it: `d39a56a` is the closest `master` commit to the
imported `packages/aec`. The 2026-10-08 import also carried later revisions of the then-open draft PRs #80–#91. Those
are why #100 was mostly a no-op here.

## Upstream commits (Ontology `master`, first parent, after `d39a56a`)

| Ontology commit | PR | Status | Platform commit | Notes |
|---|---|---|---|---|
| `d636404` | #94 ArchiOffice pack as GraphRAG project | already ported | `61256a3`, `891418b`, `cfc55b8` (2026-10-09) | Re-applying it gave an empty diff. The pack tools keep the platform's ruff fixes |
| `36f8849` (`952a015`, `233ba43`) | #96 drop Windows profile name from ArchiOffice paths | already ported | `891418b` | Empty diff |
| `6a476a2` | #97 Google Drive CAD pack (`library/gdrive_cad`) GraphRAG project | **ported** | `e9bd7eb` | Clean. `graphrag/ask.py`, `commands.py`, `parsers.py`, `embeddings.py`, `test_graphrag_pack_drawings.py` |
| `743352a` | #98 gdrive_cad doc numbers + two backup script fixes | **ported** | `e7cced3` | Clean. Follow-up commit `52b6779`: `restore_db.sh` now uses the same default remote as `backup_db.sh` (upstream left them different) |
| `b955b5c` | #95 ArchiOffice pack load review fixes | **ported** | `7527c89` | Clean. Adds `tests/test_archioffice_pack_tools.py` |
| `bb7f2a3` | #99 netguard never trusts DNS; Pillow/PyMuPDF in dev extra | **ported (conflict)** | `f5e625f` | Took upstream `netguard.py`; see "Conflicts" |
| `d81598f` | #100 integrate read-only bridge drafts (#80, #83, #84, #86–#91) | **ported (mostly present)** | `630daca` | Kept the platform's stricter copies. Added `PROGRESS.md`, `docs/audits/*` (4) and `test_host_provider_mismatch_is_rejected`. Its CI workflow is not ported |
| `0e2db4d` | #102 interrupted work, Python 3.13, E2E smoke harness, pgvector guard, pg client match; includes the #101 ArchiOffice prune-before-relink fix | **ported (conflict)** | `c04de86` | `backup.py` and `load_archioffice.py` merged by hand. CI workflow changes not ported |
| `bf447df` | #103 consolidation plan + producer-side contract test | **ported** | `f851bad` | `tests/contracts/aec-cair-snapshot-1.schema.json` is byte-identical to `sion_core`'s copy. The plan document is not duplicated |
| `8938175` | #104 storey from frames/layers/level text; operational CLI loads `.env` | **ported (conflict)** | `984a17d` | `parsers.py`: kept the platform's sheet-number collectors (#51) and added `level_texts` |

Open Ontology PRs are not merged upstream, so they are not ported. #101 is covered by #102. #80–#91 are covered by #100.

### Conflicts and how they were resolved

- **`operational/netguard.py` (#99).** The platform had its own fix from 2026-10-08: resolve DNS, but reject the
  198.18.0.0/15 fake-IP range, with a `_getaddrinfo` test seam. Upstream #99 (2026-10-17) never consults DNS. Only
  literal local IPs in explicit RFC1918/loopback/link-local/ULA ranges, the built-in names (`localhost`,
  `host.docker.internal`, `ollama`, `embeddings`, `gateway.docker.internal`, `*.localhost`) and the operator allow-list
  `AEC_LOCAL_HOSTNAMES=a,b` count as local. Upstream is newer and stricter, so it was taken. `tests/test_netguard.py` and the two
  `_public_dns` helpers were rewritten for it: DNS is now forbidden in those tests, and a LAN host passes only through
  the allow-list. **Opt-out for a LAN GPU box:** set `AEC_LOCAL_HOSTNAMES=gpu-box.lan`, or use a literal IP. Remote
  endpoints still need `AEC_EMBEDDING_ALLOW_REMOTE` / `allow_remote`, as before.
- **`readonly_bridges/evidence.py`, its CLI/evidence tests, `scripts/ops/bulk-run.ps1`, `tests/test_worker_readiness.py`
  (#100).** These are add/add conflicts. The platform copies came from later draft revisions and are strict supersets.
  `_validate_probe_projection` refuses catalog or hand-written projections. `bulk-run.ps1` passes the
  `AEC_MIN_AVAILABLE_MB` fallback to the workers. The platform copy has more worker readiness tests. The platform side
  was kept. Upstream's only new test (host/provider mismatch) was added.
- **`docs/OPERATIONS.ko.md` (#100).** Kept the platform text from #111 (midnight-safe repeat triggers, Docker-Startup task).
- **`operational/backup.py` (#102).** Kept the platform's in-container `pg_dump` + `docker cp` path (#76). Added
  upstream's server-version-matched client lookup `_tool(..., server_major(dsn))` for host binaries.
- **`library/archioffice/tools/load_archioffice.py` (#102).** Took upstream's early manifest parse. It is an expression
  statement, so the platform's ruff fix for the unused variable still holds.
- **`operational/parsers.py` (#104).** Both sides added fields in `_DXFSemantics.__init__`. Both were kept.

### Not ported (with reason)

| Path / change | From | Reason |
|---|---|---|
| `.github/workflows/*` (drawing-context-headless, external-capabilities, intelligence-safety: 3.12/3.13 matrix, DB no-skip gate, E2E job) | #100, #102 | `packages/aec/.github` is not run in the monorepo. CI for `packages/aec` is `.github/workflows/aec.yml`, which already runs the core, intelligence-fabric, drawing-context and external-capabilities suites. The E2E smoke job is a follow-up (see below) |
| `docs/CONSOLIDATION_PLAN.md` | #103 | Already at the monorepo root (same document) |
| `docs/CLOUD_COMPLETION_2026-11-05.md`, `docs/ROLE_IN_ECOSYSTEM.md` | #103 | Ontology repository metadata. The monorepo has its own copies at the root |

## Contract `aec-cair-snapshot/1`

`tests/test_aec_cair_ingest_contract.py` passes (15 tests, including the live bundled DXF/IFC round trips). The bundled
`packages/aec` CLI output for `simple_house.dxf` / `simple_house.ifc` (project ids `simple-house-dxf` / `simple-house-ifc`)
was compared field by field with the pinned fixtures. The object ids, types, properties, relationships and metadata are
identical. Only timestamps (`created_at`, `provenance.timestamp`, `version.valid_from`), `snapshot_id` and the source
path spelling differ. The #104 storey fill does not touch these fixtures, so the fixtures and
`upstream_commit = d81598f` are **unchanged**.

## Verification (cloud, 2026-11-09, Python 3.13)

| Command | Result |
|---|---|
| `uv pip install -e ".[aec,dev]"` (root) + `packages/aec[dev,cad,bim,shacl,semantic,parquet,operational]` | ok |
| `ruff check .` (root) and `ruff check src tests extensions` (packages/aec) | passed |
| `pytest` in `packages/aec/tests` | 908 passed, 53 skipped (PostgreSQL tests: no DB in this container) |
| extensions: intelligence_fabric / drawing_context / external_capabilities | 13 / 135 / 116 passed |
| `python -m compileall -q src extensions` | ok |
| `pytest` (root: `tests` + `packages`, `[aec,dev]` extras) | 1971 passed, 59 skipped (incl. `tests/test_aec_cair_ingest_contract.py`, 15 passed) |

Not run here: the PostgreSQL-backed suites and `scripts/e2e/e2e_smoke.py`. The AGE/pgvector image could not be built
for lack of disk space in the container. CI job `aec-operational-postgres` runs the DB suites.

## Follow-ups

1. Owner: freeze Ontology `master` at **`8938175`**: README banner, branch protection, CI only. Any later commit
   on Ontology `master` must be replayed the same way before the freeze.
2. Wire `packages/aec/scripts/e2e/e2e_smoke.py` into `aec.yml` (`aec-operational-postgres`, after the DB tests) and add
   a 3.13 leg to the aec job.
