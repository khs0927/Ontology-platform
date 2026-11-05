# Cloud work completion, 2026-11-05

This file is identical on PR #100 and PR #101, so merging both does not conflict.

## Local Windows run (2026-11-05)

Host: Windows 10, Python 3.12.10, fresh clone. `SION_*` environment variables were unset for the final runs.

### PR #100 (GraphRAG rejected relations)

| Command | Result |
|---|---|
| `uv lock --check`, `uv sync --locked --extra all --extra dev` | passed |
| `ruff check .` | passed |
| `python scripts/check_public_privacy.py` | 0 findings |
| `pytest` (root, final) | 853 passed, 7 skipped |

The first run failed one test. `test_config_requires_embedding_model` read `SION_GRAPHRAG_STORAGE=local` from the workstation environment, so the test now clears that variable. It passes with the variable set and unset.

Open: after merging, re-project once into a fresh `SION_GRAPHRAG_WORKSPACE` so previously projected rejected rows are gone.

### PR #101 (regulation review W05–W13)

| Command | Result |
|---|---|
| `pytest` (root) | 922 passed, 7 skipped |
| `pytest` in `packages/regulation` | 270 passed, 39 skipped (PostgreSQL integration tests need `ARCHONTOS_TEST_DATABASE_URL`; CI runs them) |
| `ruff check .` at the root and in the package, `ruff format --check .`, `mypy` in the package | passed |
| `python scripts/check_public_privacy.py` | 0 findings |
| `/regulation` in a browser against a local server with SQLite | scope plan, run, briefing and save worked, no console errors |

Scenarios S01–S32 are synthetic processing tests. They are not legal answers and the release metrics were not measured.

Open, with details in `docs/regulation/IMPLEMENTATION-STATUS.md`:

- The `aec-mcp-router` adapter is not done. Its source is not on this PC or in the GitHub account, so the MCP tools are documented as REST mappings only.
- No real provider executors, official data or reviewed rules are connected. Without a bundle every checklist row stays unresolved.
- W02, W03 and W14 need decisions and reviewed data from people. D01–D10 are not closed.
- The LightRAG index has not been tested with the scoped projection.
- The new REST routes were not run on PostgreSQL locally.
