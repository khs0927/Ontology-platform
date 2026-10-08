# CI

Full pytest runs on Ubuntu only. Windows runs the GOD-CAD package tests, not the monorepo suite.

| Workflow | Job | OS | What runs |
| --- | --- | --- | --- |
| `tests.yml` | `pytest` | `ubuntu-latest` | `python -m pytest` after `.[all,test,dev]` |
| `tests.yml` | `uv-locked` | `ubuntu-latest` | `uv run --locked pytest` |
| `verify.yml` | SQLite and API tests | `ubuntu-latest` | `python -m pytest -q` after `.[test]` |
| `aec.yml` | GOD-CAD | `ubuntu-latest`, `windows-latest` | pytest in `packages/cad/god-cad` only |

A full `windows-latest` pytest job was prepared locally as `ci/windows-pytest` (`22e468a`) but not pushed. This token cannot update `.github/workflows` without the `workflow` scope (`issue #33`).

SketchUp `python -m sion_ingestion.sketchup_assets build --check` is not a workflow step on `main`. On PR #31 it runs inside `tests/test_sketchup_assets.py` for the same scope reason.
