# NVIDIA Auto Ontology × Sion: read-only federation pilot

Status: **implemented adapter + mocked API contract tests**; **NOT deployed**, not
connected to a live NVIDIA service, no claim of improved query accuracy. Production
ingestion, semantic compilation and credential provisioning are deliberately out of
scope. This is NOT a substitute for canonical Sion knowledge or ArchOntos.

## Revisions and licensing

- Sion base: khs0927/Ontology-platform at a89a9f263e0176e00a95a0c1644a43bd8f2abe62
- NVIDIA: https://github.com/NVIDIA/auto-ontology at
  c447003f72a822301e927196a4ecb5b597c308d5 (Apache-2.0)
- NVIDIA's documented authenticated public API:
  - GET /api/terms?query=&skip=&limit= (see auto_ontology/server/terms/router.py)
  - POST /api/chat/completions, SSE (see docs/conversation-api.md)
- Uses Sion's existing httpx dependency. No NVIDIA Python code is copied. No
  database migration, Docker deployment or new source-data ingestion is performed.

## Enable in a separately reviewed environment

NVIDIA must already be provisioned on a network-reachable host. Point at its
**Next.js authenticated gateway** (usually port 3000), not its internal FastAPI
backend (usually port 3001). The latter trusts an internal identity header.

Configure **server-side** variables only; never commit their values:

    SION_NVIDIA_AUTO_ONTOLOGY_URL=https://your-nvidia-gateway.example
    SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN=<<<viewer API token held only in secret storage>>>
    SION_NVIDIA_AUTO_ONTOLOGY_ENABLE_ASK=false
    SION_NVIDIA_AUTO_ONTOLOGY_TIMEOUT_SECONDS=120

Get a role-limited, preferably expiring viewer API token through NVIDIA's
UI > API Tokens. If URL and token are absent, federation is disabled.
Configuring one without the other prevents startup rather than exposing a
half-configured bridge. Only HTTPS origins (or loopback HTTP for tests) are
accepted; redirects are not followed. The bridge does not read proxy variables.
No customer documents or private drawings should be connected to NVIDIA without
a separate data-access/privacy review.

## Routes

Existing Sion read:knowledge authentication applies and project-allowlisted
tokens are **refused** because the remote NVIDIA catalog is not yet scoped by
project. This is deliberate and preserves fail-closed isolation.

- GET /api/v1/nvidia/status : local configuration status only, no upstream
  call. upstream_verified=false even if a URL is configured.
- GET /api/v1/nvidia/terms?query=door&limit=20 : uses NVIDIA's authenticated
  glossary. Returns candidate Sion Concepts, always verification_state=unverified
  and promoted=false. NVIDIA-certified names are NOT human verified Sion facts.
- POST /api/v1/nvidia/ask : {"question":"How many doors?"}, requires
  SION_NVIDIA_AUTO_ONTOLOGY_ENABLE_ASK=true. The upstream NVIDIA agent runs
  any SQL using its own configured connection. Sion returns the SQL/results as
  advisory data with canonical=false and never executes SQL or writes graph rows.

No endpoint calls NVIDIA compilation, catalog reset, connection management,
DB mutation or term promotion. The bridge has bounded responses, results and
errors; API tokens are excluded from responses and logs.

## What is not provided yet

1. A deployed NVIDIA server + PostgreSQL catalog with an approved source schema
   and a confirmed read-only account.
2. A project-safe semantic materialization: Sion must expose approved, filtered
   SQL views (project, ACL, effective time, review state); do NOT attach NVIDIA
   directly to unrestricted Sion canonical tables.
3. Sion reviewer-approved mapping from NVIDIA Term/SQL attributes to canonical
   LinkML/SHACL entities, relations and Evidence, preserving source IDs, version
   and original assertions.
4. Identical questions and verified answer keys for A/B/C accuracy, speed,
   inference usage and token-cost tests before enabling NVIDIA-by-default.
5. Project-allowlisted federation; currently 403 rather than leaking data.

## Local tests (do not require NVIDIA credentials or deployment)

    uv sync --locked --extra all --extra dev
    uv run --locked pytest tests/test_nvidia_auto_ontology.py tests/test_api_scopes.py -q
    ruff check apps/api/sion_api/nvidia_auto_ontology.py tests/test_nvidia_auto_ontology.py

If upstream modifies the API, update the pinned revision, integration contract
and recorded tests together. Do not auto-update images or silently migrate Sion.
