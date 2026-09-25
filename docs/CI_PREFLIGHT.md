# CI preflight

## Scope

This preflight validates `.github/workflows/ci.yml` without modifying the workflow. The gate is deliberately fail-closed: actionlint runs first, then a PyYAML and repository contract check runs. Any error, download/hash failure, unavailable Python/PyYAML, or missing executable is a blocker.

Run from the repository root:

```powershell
pwsh -NoProfile -File scripts/validate-workflows.ps1 `
  -WorkflowPath .github/workflows/ci.yml `
  -Python .\.venv\Scripts\python.exe
```

The script downloads actionlint `1.7.12` for Windows into a newly-created system temp directory, verifies the release archive SHA-256, executes `actionlint.exe`, and removes the directory in `finally`. It does not install a package or write into the repository. Supply `-ActionlintPath` to use an already-reviewed local executable. `-AllowContractFallback` is an explicit exception for environments where actionlint cannot be obtained; output must state the fallback, and it is not equivalent to a passing real-linter gate.

## Contract checked

- PyYAML parses the workflow and preserves the `on` key despite PyYAML 6's YAML 1.1 behavior.
- top-level permissions are exactly `contents: read`;
- concurrency exists;
- expressions have balanced delimiters and reject known untrusted pull-request secret access;
- every `needs` target exists;
- every action is pinned to a full 40-character commit SHA;
- every `run` step has explicit shell intent in the contract test, and actionlint remains authoritative for expression/context and shell errors;
- every service has an image and health options;
- job and service `env` values are mappings, and environment-sensitive jobs remain isolated.

## Current result and blockers

Validated on Windows in the local repository clone:

- actionlint was obtainable and executed from a temporary directory.
- The earlier actionlint blocker is **resolved**: every `run` step in `.github/workflows/ci.yml` now declares an explicit `shell: bash`, and the repository contract check no longer reports the shell omission. The workflow change belongs to the P1 remediation working tree, not to this documentation task.
- No other blocker was inferred from the inspected YAML: `needs` has no dangling target, action references are full commit SHA pins, service images and health options are present, and top-level permissions are `contents: read`.
- A passing local validator run is **local contract evidence only**. It is not a hosted CI run and must not be recorded as one.

## Hosted evidence: blocked

- GitHub-hosted Actions **cannot run** because of the billing/spending limitation, so none of the required jobs (`pytest-suite`, `alembic-revision-contract`, `postgres-core`, `postgres-pgvector`, `resource-wheel-contract`, `secret-scan`) has a hosted conclusion.
- Billing-blocked, cancelled, skipped, or absent runs are recorded as **blocked**, never as successful CI. No workflow workaround may convert a billing failure into a success.
- Branch protection on `main` is reported **false**, so no required-check enforcement exists even once a run is possible. Enforcement must be enabled by the repository owner.
- The workflow is therefore **not** merge- or release-ready. Re-run the validator and capture the hosted run URL, commit SHA, and per-job conclusions after billing is resolved and the branch is pushed.
