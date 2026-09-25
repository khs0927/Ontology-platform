# Harden P0/P1 release controls for the ontology platform

> **State: prepared for code review.** Base commit `715ea4c0827b74328b5edf852be844472eaf7c96` on `codex/p0-remediation-20260924`, with the P1 remediation wave included in this PR. The user approved submission of the branch and pull request. Hosted CI may remain billing-blocked. Nothing here claims a hosted CI success, a release, a signature, or a deployment.

## Summary

This branch hardens the ontology platform's P0 control plane and completes the P1 remediation wave across the API, DLP/ingestion boundary, migrations, bridge publication, packaging metadata, and CI contracts. The base for review is `715ea4c`, and remote `main` is still at `44c3ec0`, so this PR represents the full P0+P1 delta at once.

### P0 (in base commit `715ea4c`)

- Local bearer-token auth guards; loopback default with explicit non-loopback configuration requirements.
- Liveness vs. dependency/schema readiness separation on the health endpoints.
- DLP scanning, redaction, and fail-closed ingestion behavior with no persist-on-block semantics.
- Alembic `0001_baseline` through `0004_schema_parity`, with PostgreSQL 16 / `pgvector/pgvector:0.8.6-pg16` rehearsal of upgrade, seed, constraints, vector insert/search, and the non-destructive downgrade to `0002_evidence_contract`.
- Clean wheel / sdist / editable install rehearsals with SHA-256 resource hash comparison.
- Release-lock verification and atomic release-metadata generation.
- PyInstaller 6.22.3 frozen-bridge rehearsal with external data root and no-persist checks.
- Atomic, non-destructive sync publication with prior-backup preservation.
- CI workflow contracts for tests, Alembic revisions, PostgreSQL core, PostgreSQL/pgvector, resource/wheel validation, and secret scanning.

### P1 fixes (in this PR delta)

- **API write-sink DLP enforcement**: DLP now runs on API write paths, not only on the bridge CLI.
- **Bound DLP decisions**: allow decisions are bound to content digest, HMAC, policy version, and freshness, so a decision cannot be replayed against different content or a stale policy.
- **Endpoint-inclusive edge hashing**: graph edge hashes include the endpoint identity, preventing cross-endpoint edge collisions.
- **Staged bridge publication**: bridge output is published via a staging step with read-back verification, and an explicit DB commit point replaces the previous write-then-verify ordering.
- **Source / `cwd` policy fixes**: the bridge and ingestion packages no longer depend on the checkout source path or an implicit `cwd`.

### Supply-chain hardening (in this delta)

- Signing preflight accepts **only** Authenticode `Valid` as a trusted release candidate. `NotSigned`, `NotTrusted`, `UnknownError`, `Unavailable`, and `HashMismatch` are blocking states, and the report exposes `accepted_statuses` / `blocked_statuses` explicitly.
- Release metadata generation is atomic, rejects unsafe output paths, and does not copy environment secrets.
- SBOM generation is honest: with no generator available the record reports `status: blocked` with an unavailable-tools blocker, no `sbom.json` is written, and no components are fabricated.

## Test plan and results

**Local verification (the only verification that currently exists):**

- `python -m pytest` -> **357 collected, 0 failed**. A portion are skipped on environment-dependent preconditions (missing optional dependency, unavailable local service). The 357/0 figure is a recorded local observation, not a live measurement and not a release gate by itself.
- `python -m compileall -q packages apps sync tests` -> passing.
- `python -m pip check` -> passing.
- `git diff --check` -> clean.
- Docker PostgreSQL 16 + `pgvector/pgvector:0.8.6-pg16` rehearsal -> migrations, seed/constraints, vector search, readiness, and non-destructive downgrade passed locally. Temporary container and volume removed.
- Clean wheel / sdist / editable install probes -> resource, CLI, Alembic, application-construction, and resource-hash checks passed locally.
- PyInstaller 6.22.3 build -> help, qualified imports, external `SION_DATA_ROOT`, and four packaged resources verified locally. DLP-blocked dry run exits 1 by design; that exit code is a contract-valid outcome and was not suppressed to force a zero exit.

**Superseded earlier claims:** the previous smaller baseline, a duplicate test-module collection report, and a signing-preflight byte-size mismatch are all resolved and withdrawn. See `docs/REVIEWER_CHECKLIST.md` for the current validation record.

**Hosted CI: not run.** GitHub-hosted Actions is billing-blocked, so no hosted job conclusion exists for any job in this PR. Billing-blocked, cancelled, skipped, or absent runs must not be read as green.

## Security

- Loopback remains the default; non-loopback binding requires `SION_LOCAL_API_TOKEN` plus a bearer token. This is a local control, **not** production identity or authorization, and is not approval for public deployment.
- DLP is enforced on API write sinks and at the bridge boundary, with fail-closed and no-persist behavior on block. Allow decisions are bound to digest, HMAC, policy, and freshness.
- No credentials, API keys, tokens, or private keys are introduced. The workflow includes secret scanning.
- Bridge publication is staged with read-back verification before a DB commit point, so a partially published artifact cannot be recorded as published.
- Runtime packages no longer resolve from the checkout source path or an implicit `cwd`, removing a source-tree dependency from the frozen and installed paths.
- Supply-chain posture is deliberately fail-closed: unsigned provenance stays `signature_status: not_signed` / `verified: false`, and a missing SBOM generator produces a `blocked` record rather than fabricated components.

Reviewers should focus on: the security boundary and auth guards, DLP fail-closed semantics, migration upgrade/downgrade behavior, package contents and resource hashes, and sync/bridge atomicity.

## Rollback and recovery

- No production deployment, migration, or release has been performed by this branch, so production rollback is **not exercised and still required**.
- Before any production migration: verified backup, named migration owner, change window, and an explicit rollback decision are prerequisites.
- `alembic downgrade 0002_evidence_contract` is the rehearsed non-destructive vector path. Arbitrary destructive downgrades are not implied safe and must not be run against production data without an approved runbook and backup verification.
- If a future hosted CI run fails, merge is blocked by review, not by tooling: branch protection is reported `false` on `main`, so there is **no required-check enforcement** to catch it automatically.
- Sync and bridge publication are staged: on failure the prior state is retained, and recovery is manual and explicit rather than silently presented as successful multi-sink delivery.
- Packaging failure recovery is a clean rebuild into an isolated output directory; no in-place artifact mutation is performed.
- The DLP-blocked dry-run exit code 1 is intentional. Do not suppress it to obtain a zero exit.

## Risks and known limitations

This branch is **not** production-release-ready.

1. **Hosted CI is billing-blocked.** No hosted run, no job conclusions, no required evidence. The PR cannot be claimed as CI-verified.
2. **Branch protection on `main` is reported `false`.** Required checks are not enforced; do not infer enforcement from the presence of a workflow file. The repository owner must enable it.
3. **Windows Authenticode signing is blocked.** Both the committed `bin/sion-agent-bridge.exe` and freshly built PyInstaller output are `NotSigned`; `signtool` / Azure Trusted Signing are unavailable. Detect-only. The committed EXE is unsigned and must not be distributed.
4. **SBOM generation and attestation are blocked.** No `cyclonedx-py`, no `syft`, no `sbom.json`, no trusted provenance verification. Provenance remains unsigned and unverified.
5. **Migration work is review-required.** Alembic branch/integration work and production migration evidence are incomplete. Local Docker rehearsal is not production migration approval.
6. **Local API auth is not internet-grade.** No public deployment approval exists.
7. **Incomplete end-to-end paths.** End-to-end document ingestion and evidence extraction, complete DLP policy enforcement, authenticated Drive upload and scheduler registration, the exact 43-edge structured map export, GraphRAG, and CAD/BIM extraction all remain open.
8. **Advisory scores are not approval.** Jev's local P0 score of 2.97/4 and its roughly 98% external-gate block are advisory readiness signals only.

## External blockers

| Gate | Status | Owner action required |
|---|---|---|
| GitHub-hosted CI | Blocked by billing/spending limit | Restore runner capacity or provide an independently approved equivalent runner |
| Branch protection / required checks | Reported `false` on `main` | Repository owner must enable and confirm required checks |
| Windows Authenticode signing | Blocked (`NotSigned`, no signing tooling) | Provide approved signing path and certificate/Trusted Signing |
| SBOM + attestation | Blocked (no generator available) | Provide an approved SBOM generator and attestation workflow |
| Production migration evidence | Pending / review-required | Runbook, backup verification, migration owner, change window |
| Public deployment | Not approved | Production identity/authorization design required |
| Push and PR | Approved by user; this PR is the submission | Record the hosted run URL, exact SHA and job conclusions after submission |

## Decision

**Requested decision: review and approval to merge this branch as a fail-closed hardening change. Release remains BLOCKED.**

- Merge: acceptable on code review. The local evidence above supports review of the implementation, rehearsals, and contracts.
- Release: **not requested and not approved.** Do not publish, sign, deploy, or ship any artifact from this PR.
- Merge must not be justified by CI: hosted CI is billing-blocked and required checks are not enforced, so the reviewer is the enforcement gate here.
- This PR must not be read as evidence that the branch is verified, signed, attested, deployed, or released.

Reviewer checklist: `docs/REVIEWER_CHECKLIST.md`. Release gate preflights: `docs/CI_PREFLIGHT.md`, `docs/GITHUB_PREFLIGHT.md`, `docs/SIGNING_PREFLIGHT.md`.

## Non-actions in this change

This change intentionally does not:

- change billing, spending limits, branch protection, or any repository setting;
- purchase a certificate or sign any artifact;
- generate an SBOM or claim trusted provenance;
- publish a release, deploy, or run a production migration.

This PR is the local P0/P1 remediation change. Hosted CI, signing, SBOM, production migration, and release remain external evidence gates.
