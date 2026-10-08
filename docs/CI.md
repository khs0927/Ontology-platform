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

## Workflows

| Workflow | File | Trigger | What it checks |
|---|---|---|---|
| Tests | `tests.yml` | PR / push to main | ruff, full pytest with all optional extras, wheel + sdist build |
| Verify | `verify.yml` | PR / push to main | minimal-install pytest (SQLite), PostgreSQL + pgvector migration replay |
| Hindsight advisory memory | `hindsight-advisory.yml` | PR touching advisory memory | advisory memory tests |
| Release agent bridge | `release-agent-bridge.yml` | PR touching bridge sources, `v*` tag, manual | Windows PyInstaller build of `sion-agent-bridge.exe`, `--help` smoke test; on tags attaches exe + sha256 to the GitHub Release |
| CircleCI | `.circleci/config.yml` | every push | mirror of `tests.yml` |
| Public repository security | `security.yml` | PR / push / manual | personal information check and audit of all locked optional dependencies |

### Releasing the Windows agent bridge

The exe is no longer committed (it was ~37 MB per build). To publish a new one:

```bash
git tag v0.2.1 && git push origin v0.2.1   # workflow builds and attaches the exe
```

or run the workflow manually with an existing tag as input.
