# Upstream: khs0927/Ontology

`packages/aec` is the monorepo copy of [khs0927/Ontology](https://github.com/khs0927/Ontology) (`aec_intelligence`).
Edit it here. The upstream repository is being frozen (docs/CONSOLIDATION_PLAN.md, phase 2).

- Imported 2026-10-08 from Ontology `master` @ `d39a56a`. The import came from a filter-repo copy, so the hashes
  differ and `git subtree pull` does not work.
- **In sync with Ontology `master` @ `7c35364`** (`7c35364b75cb14a2e4c43b3b039fadea09d6ea00`, #105), as of 2026-11-09.
  Each commit is listed in [`docs/AEC_CATCHUP_2026-11-09.md`](../../docs/AEC_CATCHUP_2026-11-09.md). The platform
  commits carry an `Upstream-Commit:` trailer.

## Intentional differences from Ontology @ 7c35364

A tree diff against Ontology @ `7c35364` shows only the items below. The diff leaves out `.github/`,
`docs/CONSOLIDATION_PLAN.md`, `docs/CLOUD_COMPLETION_2026-11-05.md` and `docs/ROLE_IN_ECOSYSTEM.md`.

| Area | Files | Why |
|---|---|---|
| DXF reading via the shared `sion_cad.reader` | `src/aec_intelligence/dxf.py` | One DXF reader for every lane (monorepo phase 0) |
| Title-block drawing-number extraction (platform #51) | `classifier.py`, `operational/parsers.py`, `tests/test_title_block_text_number.py` | Platform feature, not in upstream |
| `/v1/search` `model` hint (422 on mismatch) | `operational/api.py`, `tests/test_search_model_hint.py` | power-cad-mcp contract |
| Hardening from the review rounds | `mcp_http.py`, `operational/{auth,catalog,cli,worker}.py`, `dashboard.py` and their tests | Platform-side fixes made after the import |
| Local-first backup + docker-cp mirror (#76), version-matched client from upstream #102 | `operational/backup.py`, `scripts/ops/backup.ps1`, `tests/test_backup_docker_mirror.py` | Multi-GB dumps through `docker exec` stdout broke on Windows |
| `restore_db.sh` default remote = `gdrive:AEC-INTELLIGENCE/backups` | `scripts/ops/restore_db.sh` | Upstream #98 moved only `backup_db.sh` |
| Read-only bridge evidence: strict probe-projection validation | `extensions/external_capabilities/readonly_bridges/{evidence.py,README.md}` and tests | Later draft revision than the one upstream #100 integrated |
| Bulk/worker readiness extras | `scripts/ops/bulk-run.ps1`, `tests/test_worker_readiness.py` | Same as above |
| Task registration past midnight, Bulk-Observe/Docker-Startup tasks (#111) | `scripts/ops/register-*.ps1`, `docs/OPERATIONS.ko.md`, `tests/test_register_tasks_ops.py` | Platform ops fix |
| Monorepo switch-over | `scripts/ops/switch-to-monorepo.ps1`, `docs/SWITCH-TO-MONOREPO.ko.md`, `tests/test_switch_to_monorepo_ops.py` | Monorepo only |
| Image built from the monorepo root | `docker/Dockerfile.app`, `docker/Dockerfile.app.dockerignore`, `docker-compose.yml` | `docker build -f packages/aec/docker/Dockerfile.app .` |
| netguard tests for the no-DNS rule | `tests/test_netguard.py`, `_public_dns` helpers | Upstream #99 semantics, platform tests |
| Generated registry/dashboard exports, docs wording | `global/00_GLOBAL/*`, `global/10_EXPORTS/dashboard/*`, `docs/drive-integration.md`, `docs/verification-boundary.md`, `README.md`, `.gitignore` | Regenerated or reworded in the monorepo |
| `.github/` | `.github/workflows/*` | Not run in the monorepo. CI is `.github/workflows/aec.yml` |

## Replaying a later upstream commit (if Ontology changes before the freeze)

Replay the commit as a three-way patch with the upstream parent as the base. The steps are in
`docs/AEC_CATCHUP_2026-11-09.md` ("Method"). Do not use `git subtree pull`, and never `pip install` Ontology into the
platform venv: both distributions ship `aec_intelligence`.
