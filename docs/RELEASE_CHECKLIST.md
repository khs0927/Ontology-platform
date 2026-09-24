# Release checklist

This repository uses a fail-closed CI policy.

## Required before merge

- [ ] Branch is `codex/p0-remediation-20260924`.
- [ ] `python -m pytest` passes locally, including auth, DLP no-persist, Evidence XOR, bridge upsert, sync atomicity, automation security, Alembic revision, resource wheel, and frozen-contract tests.
- [ ] Required hosted jobs are present and successful: `pytest-suite`, `alembic-revision-contract`, `postgres-core`, `postgres-pgvector`, `resource-wheel-contract`, and `secret-scan`.
- [ ] PostgreSQL 16 with pgvector 0.8.6 is available in both database jobs.
- [ ] The wheel was built and installed into a clean virtual environment and resource contents were verified.
- [ ] No secrets are present in the repository.
- [ ] The reviewer confirms the diff contains only the three requested files.
- [ ] No commit or push has been made from this work; changes remain uncommitted for the primary worker.

## Hosted-run limitation

Private repositories or free plans may not start GitHub-hosted jobs because of account billing or spending limits. A billing-blocked, cancelled, skipped, or absent run is **not** a successful CI result. It is a release blocker. Do not merge or release based on it, and do not add a workflow step that converts a billing failure into success.

The repository owner must restore hosted-runner availability or provide an independently approved equivalent runner. Until then, the release decision remains blocked.

## Release evidence

Record the workflow run URL, commit SHA, job conclusions, wheel artifact, and reviewer approval in the release record. Any missing evidence is a release blocker, not an implicit pass.
