# Release Notes Draft: P0 and P1 control hardening

> **Draft, not a release.** This document describes the local evidence for base commit `715ea4c0827b74328b5edf852be844472eaf7c96` plus the P1 remediation wave in this PR. It is not a publication record and must not be used to claim hosted CI, signing, deployment, or release completion. The user approved branch submission and PR creation.

## Release theme

Harden the ontology platform's control plane and make every release gate fail closed. The intent is to prevent unsafe persistence, invalid schema transitions, incomplete packaged resources, accidental source-tree dependencies, replayable DLP decisions, partially published bridge output, and ambiguous release claims.

## What changed

### API and security boundary

- Local bearer-token protection with loopback as the default; non-loopback binding requires an explicit `SION_LOCAL_API_TOKEN` configuration plus a bearer token.
- Health and readiness distinguish liveness from dependency/schema readiness.
- DLP is enforced on API write sinks, not only at the bridge CLI.
- Loopback/non-loopback behavior, unsafe-configuration rejection, and fail-closed paths are covered by contract tests.

### DLP and ingestion (P1)

- Allow decisions are bound to content digest, HMAC, policy version, and freshness, so a decision cannot be replayed against altered content or a stale policy.
- The bridge dry-run path must not persist outputs when input is DLP-blocked.
- A DLP-blocked dry run exits 1 as an intentional contract-valid outcome; the exit code was not suppressed to force a zero exit.
- End-to-end document extraction, evidence creation, and complete ingestion policy enforcement remain unfinished.

### Schema, migrations, and vector storage

- Alembic revisions `0001_baseline` through `0004_schema_parity` are present.
- The PostgreSQL rehearsal covers schema creation, upgrade, seed behavior, relation/evidence constraints, vector insert/search, readiness, and the intended non-destructive downgrade to `0002_evidence_contract`.
- The rehearsal uses a pinned `pgvector/pgvector:0.8.6-pg16` image and removes its temporary container and volume.
- The pgvector client stays distinct from the PostgreSQL server-side extension; native `VECTOR` DDL is emitted through a dependency-free SQLAlchemy type rather than a nonexistent `postgresql.VECTOR` reference.
- Alembic branch/integration work and **production** migration evidence are still review-required. The local Docker rehearsal is not production migration approval.

### Packaging and supply chain (P1)

- Clean-room wheel, sdist, and editable installation rehearsals were recorded.
- Packaged ontology, SHACL, inventory, and example-map resources are read from installed packages and compared by SHA-256.
- Runtime packages no longer depend on the checkout source path or an implicit `cwd`.
- Release-lock verification checks exact dependency pins and release-input drift.
- Release metadata generation is atomic, rejects unsafe output paths, and does not copy environment secrets.
- Signing preflight accepts **only** Authenticode `Valid`. `NotSigned`, `NotTrusted`, `UnknownError`, `Unavailable`, and `HashMismatch` are blocking, and the report exposes `accepted_statuses` and `blocked_statuses`.
- SBOM generation does not fabricate a result: with no generator available the record is `status: blocked` with an unavailable-tools blocker, no `sbom.json` is written, and no components are invented.

### Graph and bridge publication (P1)

- Edge hashes are endpoint-inclusive, preventing cross-endpoint edge collisions.
- Bridge output is published through staging with read-back verification, with an explicit DB commit point after verification rather than write-then-verify.
- Sync retains manifests, prior device backups, local deletion records, and atomic replacement.
- The PyInstaller 6.22.3 rehearsal exercised the generated `dist` artifact, not the committed `bin` executable.
- The committed `bin/sion-agent-bridge.exe` is `NotSigned` and is **prohibited for distribution**.

### CI contracts

The workflow and its contract tests cover the local test suite, Alembic revision contracts, PostgreSQL core, PostgreSQL/pgvector, wheel and resource validation, and secret scanning. Hosted execution is an external gate and is currently blocked; it must not be inferred from local test results.

## Verification record (local only)

- **Test baseline:** 357 collected, 0 failed. Some tests are skipped on environment-dependent preconditions (missing optional dependency, unavailable local service). This is a recorded local observation, not a live measurement and not a release gate on its own.
- **Other local gates:** `compileall`, `pip check`, and `git diff --check` are passing alongside the 357-test run.
- **Packaging:** fresh wheel, sdist, and editable runtime/test-extra probes passed.
- **Database:** Docker PostgreSQL 16 + `pgvector/pgvector:0.8.6-pg16` rehearsal passed migrations, seed/constraints, vector search, readiness, and the non-destructive downgrade.
- **Frozen artifact:** PyInstaller 6.22.3 build and archive/resource checks passed; the DLP-blocked dry run exited 1 as the expected boundary.

**Superseded:** the earlier smaller test baseline, a duplicate test-module collection report, and a signing-preflight byte-size mismatch are resolved and withdrawn from these notes.

**Hosted CI did not run.** GitHub-hosted Actions is billing-blocked and produced no job conclusion. Billing-blocked, cancelled, skipped, or absent runs are not green runs.

## Risk, security, and rollback

- Local authentication is a local control, not production identity/authorization. Public deployment is not approved.
- DLP is fail-closed: blocked input persists nothing, and allow decisions are digest/HMAC/policy/freshness-bound.
- Bridge publication is staged and verified before the commit point, so a partial publication cannot be recorded as successful.
- No production deployment, migration, or release occurred, so **production rollback is not exercised and still required**.
- Before any future production migration: verified backup, named owner, change window, explicit rollback decision.
- `0002_evidence_contract` is a non-destructive boundary on the rehearsed path; arbitrary destructive downgrades are not implied safe.
- Do not distribute the unsigned committed EXE. Do not suppress the DLP-blocked exit code.

## Release status: blocked

Do not publish a production release from this draft. Open external blockers:

1. **Hosted CI billing/spending** - GitHub-hosted jobs may not start. No hosted run, no job conclusions.
2. **Branch protection** - reported `false` on `main`, so required checks are not enforced. Owner must confirm and enable.
3. **Signing** - no trusted Windows Authenticode signing evidence; committed and fresh builds are `NotSigned`, and no signing tooling is available.
4. **SBOM / attestation / provenance** - blocked; no generator available, no `sbom.json`, provenance remains `signature_status: not_signed` and `verified: false`.
5. **Production migration** - incomplete and review-required; local rehearsal is not production evidence.
6. **Public deployment** - not approved while the API is local-first.
7. **Remaining integrations** - end-to-end ingestion/evidence extraction, authenticated Drive uploader and scheduler, structured 43-edge map export, GraphRAG, CAD/BIM.

Advisory context: Jev's local P0 score of 2.97/4 and its roughly 98% external-gate block are advisory readiness signals, not release authorization and not a security attestation.

## Compatibility and rollout notes

- The API remains local-first. Do not expose it publicly without an approved identity and authorization design.
- Apply database migrations only through the reviewed deployment runbook with a verified backup and rollback procedure.
- Treat `0002_evidence_contract` as a non-destructive boundary on the rehearsed vector downgrade path.
- Do not distribute the unsigned committed EXE.
- Treat the DLP-blocked dry-run exit code as intentional.

## Artifact and provenance wording

Any metadata generated from this branch must retain its honest status:

- `signature_status: not_signed`
- `verified: false`

A checksum, SBOM, or unsigned provenance record is useful evidence, but it is not a signature and not proof of trusted publication.

## Next release gate

Before any status change to releasable: record the hosted workflow URL, exact commit SHA, and job conclusions; confirm branch protection and required checks; complete approved signing and SBOM attestation; run the production migration rehearsal under the runbook; and obtain reviewer approval. Until all of that exists, this file remains a local draft and the release state remains BLOCKED.
