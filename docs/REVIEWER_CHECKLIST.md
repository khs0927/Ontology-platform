# Reviewer Checklist: P0 control hardening

> **Fail-closed checklist for local review.** Record the exact commit, command, output, reviewer, and timestamp for every item. A local pass is not a hosted CI pass. A rehearsal artifact is not a signed or verified release artifact.

## Review context

- [ ] Confirm the reviewed base is `715ea4c0827b74328b5edf852be844472eaf7c96` on `codex/p0-remediation-20260924`.
- [ ] Confirm this documentation task adds only `docs/PR_BODY.md`, `docs/RELEASE_NOTES_DRAFT.md`, and `docs/REVIEWER_CHECKLIST.md`, plus the updates to `docs/SIGNING_PREFLIGHT.md`, `docs/CI_PREFLIGHT.md`, and `docs/GITHUB_PREFLIGHT.md`.
- [ ] Do not treat pre-existing working-tree changes from another worker as part of this three-file documentation task.
- [ ] Confirm that no billing change, branch-protection change, signing operation, or release publication was performed. Branch submission and PR creation were approved for review.

## Security

- [ ] Review loopback versus non-loopback API behavior and the required bearer-token boundary.
- [ ] Confirm the local authentication control is not described as production identity, internet-grade authorization, or public-deployment approval.
- [ ] Review secret scanning and confirm no credentials, API keys, tokens, or private keys were introduced.
- [ ] Confirm fail-closed behavior for unsafe authentication, readiness, automation, and persistence paths.
- [ ] Review automation and sync callers for untrusted input, path traversal, and accidental credential exposure.
- [x] Record the security-test command and result. The current whole-branch local run collected **357 tests** with **0 failed**. This is a local run only; it is not hosted CI evidence and must not be presented as such.

## Migrations and database

- [ ] Review Alembic revision order from `0001_baseline` through `0004_schema_parity`.
- [ ] Confirm schema creation and `alembic upgrade head` behavior in a disposable PostgreSQL 16 database.
- [ ] Confirm Evidence/relation constraints, self-loop rejection, vector shape constraints, and vector search behavior.
- [ ] Confirm the native pgvector DDL path does not require a nonexistent SQLAlchemy `postgresql.VECTOR` reference.
- [ ] Confirm `alembic downgrade 0002_evidence_contract` follows the documented non-destructive vector path and preserves the intended table, rows, and extension state.
- [ ] Confirm the destructive downgrade boundary is explicitly blocked or documented rather than inferred safe.
- [ ] Record production migration evidence as pending. The local Docker rehearsal is not a production migration approval.

## Packaging and supply chain

- [ ] Build fresh wheel and sdist artifacts in an isolated output directory.
- [ ] Install wheel, sdist, and editable packages in separate clean virtual environments.
- [ ] Confirm runtime imports do not depend on the checkout/source path.
- [ ] Verify installed ontology, SHACL, inventory, and example-map resources are readable and hash-identical across runtime installs.
- [ ] Verify the bridge console entry point, Alembic CLI/import, application construction, and test-extra health smoke.
- [ ] Run `python scripts/verify-release-lock.py` and record exact pins and hashes.
- [ ] Confirm release metadata generation is atomic, rejects unsafe output paths, and does not copy environment secrets.
- [ ] Confirm provenance remains `signature_status: not_signed` and `verified: false` until a trusted signing process exists.
- [ ] If an SBOM is unavailable, confirm the record reports unavailable rather than fabricating components.

## DLP and ingestion

- [ ] Review scanner, redaction, fail-closed, and no-persist behavior in the DLP unit and integration contracts.
- [ ] Confirm a DLP-blocked dry run exits with the documented blocked outcome and does not write outputs.
- [ ] Confirm `_MEIPASS` is not used as the data root and the configured external data root remains empty for the blocked rehearsal.
- [ ] Do not suppress or reinterpret the expected exit code solely to make the rehearsal return zero.
- [ ] Record the remaining scope: end-to-end document extraction, evidence creation, and complete ingestion policy enforcement are not yet complete.

## Sync and bridge recovery

- [ ] Confirm sync uses content-addressed staging and manifests without deleting prior device backups.
- [ ] Confirm local deletion records and atomic replacement behavior are covered by tests.
- [ ] Confirm partial failure, retry, and manual recovery behavior are explicit rather than silently represented as fully successful multi-sink delivery.
- [ ] Confirm the PyInstaller rehearsal checks the generated `dist` artifact rather than the committed `bin` executable.
- [ ] Confirm qualified imports and all required resource payloads are present in the frozen archive.
- [ ] Treat the existing committed `bin/sion-agent-bridge.exe` as unsigned and prohibited for distribution.

## CI and hosted evidence

- [ ] Run the local `python -m pytest` command and record the exact collected/skipped/passed/failed counts.
- [ ] Review required hosted jobs: `pytest-suite`, `alembic-revision-contract`, `postgres-core`, `postgres-pgvector`, `resource-wheel-contract`, and `secret-scan`.
- [ ] Record the hosted workflow URL, exact commit SHA, job conclusions, and artifact links when a run is available.
- [ ] Treat billing-blocked, cancelled, skipped, or absent GitHub-hosted runs as **blocked**, never as successful CI. Hosted CI is currently billing-blocked and has produced no job conclusion.
- [ ] Branch protection on `main` is reported `false`, so no required-check enforcement exists; do not infer it from a workflow file.

## Rollback and recovery

- [ ] Before any future production migration, require a verified backup, migration owner, change window, and rollback decision.
- [ ] Preserve the documented non-destructive downgrade path for the vector rehearsal.
- [ ] Never run a destructive downgrade against production data without an approved runbook and backup verification.
- [ ] Document recovery for failed packaging, failed migration, failed sync publication, and DLP-blocked ingestion.
- [ ] Because no production deployment was performed by this task, record production rollback as **not exercised / still required**.

## Current review validation (2026-09-24)

- [x] Current whole-branch local baseline: **357 collected, 0 failed**. The earlier smaller baseline and the six-collection-error contamination report are superseded and removed.
- [x] Repository-scoped collection is clean; no duplicate test-module discovery outside the reviewed root remains.
- [x] The earlier signing-preflight contract size mismatch (expected 10 bytes, observed 9) is resolved and removed; the signing contract asserts behavior, not incidental artifact byte size.
- [x] P1 remediation wave is complete in the working tree: API write-sink DLP enforcement, digest/HMAC/policy/freshness-bound DLP decisions, endpoint-inclusive edge hashing, staged bridge publication with read-back verification and a DB commit point, and the source/`cwd` policy fixes.
- [x] Signing preflight now accepts **only** Authenticode `Valid` as a trusted release candidate; `NotSigned`, `NotTrusted`, `UnknownError`, `Unavailable`, and `HashMismatch` are blocking states. The report exposes `accepted_statuses` and `blocked_statuses`.
- [x] Local rehearsal records stand on their own: Docker PostgreSQL 16 + `pgvector/pgvector:0.8.6-pg16`, clean wheel/sdist/editable installs, and the PyInstaller 6.22.3 frozen-bridge rehearsal all passed locally.
- [x] Confirm this documentation update edited only the four requested documents and performed no commit, push, PR, remote, signing, release, or deployment action.

## External blockers and release decision

- [x] GitHub billing/spending is **blocking hosted CI**: GitHub-hosted Actions runs remain unavailable, so no hosted job conclusion exists. The release stays blocked. Do not convert a billing failure into a success.
- [x] Branch protection on `main` is reported **false**, so no required-check enforcement exists. Do not infer enforcement from a workflow file; the owner must enable it before merge protection can be claimed.
- [x] Windows Authenticode signing is **blocked**: committed and freshly built EXEs are `NotSigned`, and `signtool`/Azure Trusted Signing are unavailable. Detect-only; do not purchase a certificate or sign as part of review.
- [x] SBOM generation is **blocked**: neither `cyclonedx-py` nor `syft` is available, so metadata records `status: blocked` with the unavailable-tools blocker, no `sbom.json` is written, and no components are fabricated. Provenance remains unverified.
- [ ] Record production migration, hosting, identity/authorization, and remaining end-to-end integration evidence as pending.
- [ ] Treat the recorded Jev **2.97/4** P0-wave score as advisory local readiness evidence, not approval. The recorded approximately **98%** external-gate block must remain visible.
- [ ] Final decision: **BLOCKED** until all external gates, required hosted evidence, signing/attestation, SBOM, production migration evidence, and reviewer approval are recorded.

## Remote and push state

- [x] The remediation branch has **never been pushed**: `git rev-parse --abbrev-ref --symbolic-full-name '@{u}'` fails with `fatal: no upstream configured for branch 'codex/p0-remediation-20260924'`, and `git ls-remote --heads origin` does not list the branch.
- [x] Remote `main` is `44c3ec0fa7972118964b24b0b9516fac598b86a4`; the reviewed local head is `715ea4c0827b74328b5edf852be844472eaf7c96`. All P0/P1 work is local-only.
- [x] The P1 working-tree delta is preserved as a patch artifact; nothing was committed.
- [ ] The user approved branch submission and PR creation. After submission, branch protection is `false`, so no required-check gate will run and the hosted CI jobs will remain billing-blocked; do not merge assuming CI enforced anything.
- [ ] After pushing, re-record the hosted run URL, commit SHA, and job conclusions. Until then hosted evidence remains blocked.

## Evidence record

| Field | Value |
|---|---|
| Commit | `715ea4c0827b74328b5edf852be844472eaf7c96` |
| Branch | `codex/p0-remediation-20260924` |
| Local test baseline | 357 collected, 0 failed (local only) |
| Docker rehearsal | PostgreSQL 16 + `pgvector/pgvector:0.8.6-pg16`; local rehearsal passed |
| PyInstaller rehearsal | PyInstaller 6.22.3; local build/contract checks passed |
| Metadata status | Not signed; not verified; `signature_status: not_signed` |
| Signing policy | Only Authenticode `Valid` is trusted; every other status blocks |
| Hosted CI | Blocked by billing/spending limitation until owner action |
| Branch protection | Reported `false` on `main`; required-check enforcement absent |
| Remote branch state | Remediation branch absent from remote; no upstream configured (never pushed) |
| Push / PR | User-approved submission; record the resulting PR and hosted run state |
| SBOM | Blocked; no `cyclonedx-py`/`syft`, no `sbom.json`, no fabricated components |
| Signing/attestation | Blocked / incomplete |
| Final release state | **BLOCKED** |
