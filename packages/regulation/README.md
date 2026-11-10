# packages/regulation — ArchOntos as a dependency

This folder intentionally contains **no ArchOntos code**. Until 2026-11 it held a
`git subtree` copy of khs0927/ArchOntos (`c911978`, plus the shared-schema option); that
copy was removed so there is one source of truth.

- **Source:** https://github.com/khs0927/ArchOntos (import package `archontos`).
- **Install:** `pip install -e '.[regulation]'` (or `uv sync --extra regulation`) installs
  `archontos @ git+https://github.com/khs0927/ArchOntos@<sha>` — the pin lives in the root
  `pyproject.toml` (`regulation` extra) and in
  [docs/INTEGRATION_CONTRACTS.md](../../docs/INTEGRATION_CONTRACTS.md).
- **Used by:** `sion_api.regulation` (rule evaluator `archontos.rules.engine`) and
  `sion_api.migrate` (ArchOntos migrations in the `regulation` schema, taken from the SQL
  shipped inside the package, `archontos._migrations`; override with
  `ARCHONTOS_MIGRATIONS_DIR`).
- **ArchOntos' own** tests, services (`apps.*`), Dockerfile and Helm chart run in the
  ArchOntos repository's CI, not here.

## Changing ArchOntos

1. Make the change in khs0927/ArchOntos (PR there, with tests).
2. Bump the SHA in the root `pyproject.toml` and `docs/INTEGRATION_CONTRACTS.md`, run
   `uv lock`, open a PR here. `tests/test_archontos_dependency.py` checks pin, lock, doc and
   the installed commit agree, and fails if an `archontos/` package is copied under
   `packages/` again.
3. Pin only commits reachable from ArchOntos `main` (exception: the head of an open
   upstream PR this repo depends on, bumped to the merge commit once it lands).

Local development against an ArchOntos checkout: `pip install -e ../ArchOntos` after the
regulation extra and set `SION_ARCHONTOS_LOCAL_OVERRIDE=1` so the pin test skips.
