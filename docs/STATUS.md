# Sion Ontology Platform — Status

Updated: 2026-09-24 (Asia/Seoul)

This is the P0 remediation intermediate state. It must not be read as a completed production release. The release gate is fail-closed: a production release is blocked until all release blockers are cleared and evidence is recorded.

## Implementation / partial / planned matrix

| Area | Status | Accurate current claim |
|---|---|---|
| LinkML, SHACL, PostgreSQL schema, provenance/evidence persistence | Implemented foundation | Contracts and storage exist; schema/migration tests cover the contract. |
| FastAPI CRUD/query, entity/relation/evidence/graph routes | Implemented foundation | Local API surface exists; no public deployment approval. |
| Local bearer authentication | Partial | Loopback remains the default; non-loopback requires `SION_LOCAL_API_TOKEN` and a bearer token. This is not internet-grade identity or authorization. |
| Alembic | Partial / branch work | Baseline migration and contract are present, but branch/integration work and production migration evidence remain incomplete. Do not infer that all upgrades are release-ready. |
| DLP module and ingestion gate | Partial | Scanner, redaction/fail-closed behavior, and tests are present; the complete ingestion gate and end-to-end policy enforcement are still being finished. |
| Multi-agent bridge | Partial | Antigravity, Codex, and Claude readers are implemented. DeepSeek, Hermes, and ZCode are registered stubs. |
| Evidence | Partial | Evidence/relation/artifact persistence and contracts exist; end-to-end document extraction and evidence creation are not complete. |
| Drive artifact layout, staging, and sync | Partial | Content-addressed staging, manifests, non-destructive sync, and atomic local replacement are implemented. An authenticated production uploader/scheduler is not complete. |
| GraphRAG | Planned | No end-to-end GraphRAG service. Any boundary is planned work, not a delivered feature. |
| CAD/BIM | Planned | No end-to-end DXF/IFC/BIM extraction. Large assets can be staged and described, but semantic extraction is not delivered. |
| CI | Blocked | Workflow and contract checks exist, but hosted GitHub jobs may be blocked by account billing/spending limits. Billing-blocked, skipped, cancelled, or absent runs are not successful CI. |
| Windows EXE release | Prohibited | Do not release an unsigned EXE. Signing and release evidence are required before distribution. |

## Current implementation

- Local PostgreSQL is the canonical target; SQLite is a smoke-test fallback.
- Map import remains non-destructive and rejects duplicate stable keys, dangling edges, and invalid counts.
- PostgreSQL/pgvector and vector round-trip foundations have been exercised, but production hosting evidence remains required.
- Artifact descriptors and logical dumps can be staged; Drive is not a live database.
- Sync preserves prior device backups and records local deletions in manifests. It is not a substitute for a managed, authenticated backup service.

## Verification baseline

This is the single source for verification commands and the test baseline. The current local run collects **357 tests, 0 failed**, with a portion skipped because of environment-dependent preconditions (for example a missing optional dependency or an unavailable local service). The count is a recorded local observation, not a dynamically generated number, and it is not a release gate on its own; README files refer here instead of restating the count.

```bash
python -m pytest
python -m pytest tests/test_api.py -q
python -m pytest tests/test_auth.py tests/test_dlp.py tests/test_evidence_contract.py -q
python -m pytest tests/test_alembic_contract.py tests/test_sync_atomic.py tests/test_ci_contract.py -q
python -m build --wheel
python -m compileall -q packages apps sync tests
python -m pip check
git diff --check
```

The last three are currently passing locally alongside the 357-test run. All of the above are local-only observations and do not substitute for hosted evidence.
Release evidence must separately record the workflow URL, commit SHA, job conclusions, wheel artifact, PostgreSQL/pgvector results, and reviewer approval. Local passing tests do not override a failed or unavailable hosted CI run.

## Current blockers

1. Hosted CI billing/spending limitation may prevent required jobs from starting. Restore runner availability or provide an independently approved equivalent runner; until then release remains blocked.
2. Alembic branch/integration work and production migration evidence are incomplete.
3. DLP/ingestion gate completion and end-to-end document evidence extraction are incomplete.
4. An authenticated Drive uploader or reliable scheduler registration is not complete.
5. Exact 43-edge migration still requires a structured Map export; endpoints must not be inferred.
6. Public deployment is not approved while the API is local-first and lacks production identity/authorization controls.
7. Shipping an unsigned Windows EXE is prohibited.

## Next milestones

1. Finish end-to-end document ingestion and evidence extraction.
2. Finish DLP gate integration and release migration evidence.
3. Complete Alembic branch work and the production migration runbook.
4. Add an authenticated Drive uploader/scheduler when a usable credential path exists.
5. Obtain and import the structured 31-node/43-edge map export.
6. Add the planned GraphRAG boundary, then separately CAD DXF and IFC/BIM adapters.
