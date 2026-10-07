# Continuous integration

The `.github/workflows/verify.yml` workflow runs on pull requests to `main`,
pushes to `main`, and manual dispatch.

It currently verifies:

- the Python API/unit suite on SQLite, with SQLite foreign-key enforcement enabled;
- the canonical PostgreSQL migrations, replayed twice against an ephemeral
  pgvector 0.8.6 / PostgreSQL 16 service;
- the expected core table count, seed counts, and `pgcrypto` / `vector`
  extensions.

This CI does not validate a production database backup, Google Drive OAuth
upload, scheduled Windows synchronization, or import of the original structured
31-node / 43-edge map. Those checks require the relevant credentials, device, or
source data and remain separate operational checks.

## Jobs (2026-10-08)

| Job | What it proves |
| --- | --- |
| `tests` | full suite with `cad`, `ifc`, `drive` extras (ezdxf, IfcOpenShell, Drive client) |
| `fallback-parsers` | same suite with core deps only: dependency-free DXF/IFC scanners still pass |
| `lint` | `ruff check .` (correctness rules configured in `pyproject.toml`) |
| `build` | `python -m build` sdist/wheel, clean-venv wheel import smoke, PyInstaller agent bridge build + `--dry-run` |
| `postgres-migrations` | 001/002/004 replayed twice on pgvector |
| `age-projection` | 001/004/005 replayed twice on `apache/age`, then `scripts/verify_age.py` rebuilds the projection twice and checks vertex/edge counts using a synthetic fixture |

Google Drive API upload is covered by a fake Drive service in
`tests/test_drive_upload.py`; a live upload still needs a real service account.
