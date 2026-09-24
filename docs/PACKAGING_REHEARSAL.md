# Packaging rehearsal

This rehearsal is an artifact-independent release gate. It builds new wheel and
sdist files into a fresh temporary directory, creates separate temporary virtual
environments, and runs from a temporary working directory with `PIP_*`, `PYTHON*`,
and `SION_*` variables removed. It never consumes an existing `dist/`, `build/`,
repository virtualenv, checkout path, or repository runtime as an installed package.

Run the gate from the repository root:

```text
python -m pytest tests/test_sdist_clean_install.py -vv -s
```

The test performs the following fail-closed checks:

1. Creates a temporary builder virtualenv and installs the `build` frontend.
2. Builds exactly one fresh wheel and exactly one fresh sdist into separate
   temporary output directories.
3. Creates separate temporary clean virtualenvs for the wheel and sdist, installs
   each artifact, and runs with the checkout/source path excluded from imports.
4. Verifies runtime package import, packaged resource reads, the
   `sion-agent-bridge --help` console entry point, Alembic CLI import/help, and
   `create_app` construction using an in-memory SQLite database. The runtime
   probe does not require `TestClient` or the test extra.
5. For each of wheel, sdist, and editable installs, creates a separate clean
   test-extra virtualenv and performs the FastAPI `TestClient` `/health/live`
   smoke request there. The editable install is likewise split between the
   runtime probe and the test-extra smoke.
6. Compares the SHA-256 hashes of all four packaged resources from all three
   runtime installs. Any mismatch is a packaging blocker.

Failures are intentionally reported as `packaging blocker: ...`; they are not
skips and do not weaken the production gate. A command failure, missing
artifact, source-path import, missing resource, CLI failure, runtime `create_app`
failure, test-extra TestClient failure, Alembic failure, or hash mismatch blocks
release until the cause is fixed. Runtime installation remains test-independent;
the test capability is exercised only in its dedicated clean environments.

## Current rehearsal result

The rehearsal was run on 2026-09-24 in the `codex/p0-remediation-20260924`
working tree after removing the unused `root = Path(__file__)...` line from the
`python -I -c` runtime probe. The probe now derives its import path from
`importlib.resources.files("sion_api.main")`, so it does not depend on
`__file__` being defined in isolated execution. Runtime and test capabilities
are now installed and verified in separate clean virtualenvs for wheel, sdist,
and editable installs.

A successful run requires all three runtime installs to pass, all three
test-extra installs to pass the `/health/live` TestClient smoke, and all three
resource hash sets to match. Any failure remains a fail-closed production-gate
failure, not a skip.
