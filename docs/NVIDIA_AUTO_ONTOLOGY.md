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


## Updated validation: real upstream NVIDIA connector with restricted Sion PostgreSQL view

The GitHub Actions run at https://github.com/khs0927/Ontology-platform/actions/runs/42377768410
tested the exact pinned NVIDIA PostgresDatabase against a disposable PostgreSQL
17 Sion schema populated with synthetic entities, relations and evidence.

Results: NVIDIA discovered exactly one project-locked view and its five
allowlisted columns, returned only two verified Project A door records, and
refused six forbidden direct reads/writes with PostgreSQL permission errors.
Project B, rejected, unverified-evidence, expired and future rows were
excluded. This does **not** test live frontend OAuth, models, semantic
compilation or actual production sources.

The CI-only SQL lives in integrations/nvidia-auto-ontology/ci. Its database
guard rejects any database other than sion_nvidia_ci. Its throwaway test
credentials must never be used for production or published as a service.

### Non-inference readiness endpoint

GET /api/v1/nvidia/readiness is scope-protected and calls NVIDIA's
GET /api/semantic-compilation/status on the authenticated frontend. It
reports semantic_calculated and compilation_running, but keeps
can_execute_sql=null because no read-only live SQL has been executed.
A successful response is **not** proof that the catalog can answer questions.
A missing server or token produces a controlled error; the API key is never
sent to the user. This probe works without any model API call.

### Still pending explicit, separately reviewed runtime setup

1. A resource-capable server running the NVIDIA app/frontend, ingestion
   service and separate catalog PostgreSQL; Railway/Render trial limits do
   not yet demonstrate that this complete stack fits without payment.
2. The actual viewer API token and HTTPS URL, added to server-side secret
   storage, plus a separately approved project-specific read-only DB export.
3. Reproducible live natural-language query benchmarks and token/usage
   measurements under an explicit spending cap.
4. No production customer documents or Sion canonical database tables may
   be attached to NVIDIA until those checks pass.

### Free ephemeral full-stack HTTP smoke

A separate workflow, \`.github/workflows/nvidia-full-stack-smoke.yml\`,
builds and starts **NVIDIA's real pinned Docker Compose** Postgres, backend,
ingestion worker, migrations and frontend **only inside a temporary public
GitHub Actions runner**. No paid runner, no production deployment, no NVIDIA
model key and no real user data.

The independent \`sion_nvidia_ci\` database holds only nine synthetic Sion
entities and a project-locked SELECT-only view. A throwaway bootstrap account
signs in to the actual NVIDIA Next.js gateway, creates an expiring API token,
and Sion's real (non-mocked) adapter calls readiness and glossary endpoints.
Sion's natural-language \`/ask\` remains DISABLED. The workflow verifies
that a configured/compiled flag never claims SQL execution without an actual
approved query.

Implementation: \`integrations/nvidia-auto-ontology/ci/prepare_ephemeral_env.py\`,
\`docker-compose.ci.yml\` and \`full_stack_smoke.py\`. It binds published
ports to 127.0.0.1, never exposes the temporary admin token, and destroys the
PostgreSQL volume at the end. Model endpoints point to unreachable loopback so
a broken test cannot spend money on inference. It does not deploy to Railway or
Render and cannot persist as a live user-facing service.

Limit: even a passing full-stack smoke does NOT prove semantic compilation,
model response quality, or a production-grade tenant ACL. Those must be
measured separately with an expressly approved credential, actual source data
authorization and hard cost/rate budget.


### Real frontend schema correction (verified from NVIDIA upstream)

The full-stack CI revealed that the NVIDIA \`GET /api/terms\` output
is **\`{"terms":[...],"total":N,...}\`**, not a \`{"data":[...]}\`
envelope. This is defined explicitly by NVIDIA
\`auto_ontology/server/responses.py:TermsPageResponse\` and
\`auto_ontology/server/terms/service.py:list_terms_page\`.
The Sion bridge was corrected to parse \`terms\`, the fixture tests now
match the pinned upstream contract, and a negative test rejects the
incorrect \`data\` variant. See PR CI history for the failing real
end-to-end run before the fix.

## 2026-11-08 — bounded live NVIDIA inference: synthetic ontology and NL2SQL

Evidence: https://github.com/khs0927/Ontology-platform/actions/runs/42491711564
CI script: integrations/nvidia-auto-ontology/ci/nvidia_synthetic_nl2sql.py
Workflow: .github/workflows/nvidia-synthetic-nl2sql.yml

This experiment is the first real NVIDIA-hosted model inference for this
PR, independent of the successful model-list-only credential probe.
Listed model: nvidia/nemotron-3.5-lightning-30b-a3b.
The first call generated an unverified synthetic Door and Project ontology
with Door PART_OF Project; structural schema validation passed.
The second call converted a synthetic natural-language door count question
into SQL. A strict in-memory SQLite authorizer denied other tables and
mutations. The generated SELECT returned exactly 2, matching the golden.

Pass: 2/2 inference calls, 364 total API-reported tokens, no retry.
The initial attempt without reasoning disabled stopped after one call
with an unusable JSON response; the verified successful run disabled
thinking using chat_template_kwargs.enable_thinking=false.
Model outputs and API keys were not logged. No real user data was sent.

Limitations: this is a direct-model synthetic pilot, NOT the official
NVIDIA Auto Ontology semantic compiler, embedded catalog, reranker,
or full upstream text-to-SQL agent. SQL executed only on synthetic SQLite
data, not on Sion production or the upstream PostgreSQL data source.
The Sion /ask flag remains off. No production deployment and no proof
of remaining free credit balance, broad SQL accuracy or safety in production.

## 2026-11-08 — 16 live NVIDIA-generated SQL goldens against PostgreSQL

CI evidence: https://github.com/khs0927/Ontology-platform/actions/runs/42494644968
Workflow: .github/workflows/nvidia-real-model-sql.yml
Implementation: integrations/nvidia-auto-ontology/ci/nvidia_model_sql_goldens.py

An NVIDIA hosted Nemotron 3.5 Lightning inference generates a fresh SQL
statement for each of 16 questions. The evaluator checks that every
statement is a single SELECT COUNT over only the security-barrier view
`sion_nv_pilot.verified_project_objects`, executes it using the actual
`nvidia_pilot_reader` PostgreSQL account, and compares the returned integer
with an independently specified golden answer. It also verifies that
selecting `public.entities` is denied by PostgreSQL permissions.

Results:
- Initial schema-only prompt: **15/16**; Door-102 mismatch.
- Exact-name prompt without sufficient ontology context: **13/16**;
  a regression that must not be hidden.
- Grounded schema + two fabricated visible sample rows + explicit semantic
  mapping (`Door-101` and `Door-102` have object_type `Concept`, not `Door`):
  **16/16**; elapsed 12 seconds across 16 real requests.

The questions include aggregates, distinct values, exact names, name prefix,
project allowlisting, rejected/unverified source exclusions, expired/future
relations and restricted Project B records. All data is synthetic.

This illustrates that ontology/schema grounding affects SQL accuracy;
it does **not** prove general accuracy on unseen data or that the official
NVIDIA ingestion/semantic compiler successfully created the grounding.
The benchmark explicitly provides schema, known project IDs and synthetic
sample rows in its model prompt. Failure results and steps are retained in
GitHub Actions; SQL text, model responses, keys and real Sion data are not
logged or persisted.

## Official upstream compiler CI (distinct from the direct-model benchmark)

Workflow: .github/workflows/nvidia-official-semantic-e2e.yml
Scripts: integrations/nvidia-auto-ontology/ci/prepare_live_models.py and
integrations/nvidia-auto-ontology/ci/official_semantic_smoke.py

This separate CI boots pinned upstream NVIDIA frontend, backend, ingestion,
and PostgreSQL with real hosted model-role configuration. It enables semantic
compilation via the official admin API, checks for persisted semantic terms,
and sends two questions through the official authenticated chat SSE API.
It uses only the project-scoped synthetic read-only Sion view; it cannot
read other canonical tables. The official compiler's validation result
is separate and must be determined from its actual workflow logs.

## 2026-11-09 — real NIM embedding, retrieval and rerank compatibility

Verified GitHub Actions run: https://github.com/khs0927/Ontology-platform/actions/runs/42496330118
Workflow: .github/workflows/nvidia-model-roles.yml
Code: integrations/nvidia-auto-ontology/ci/model_roles_probe.py

- NVIDIA nemotron-3.5-embed-1b at the advertised hosted endpoint returned
  HTTP 500 in the first isolated probe. This does not distinguish transient
  hosting failure from other server-side causes.
- The account-listed NVIDIA nemotron-3-embed-1b succeeded: 2 embedding vectors
  with 2048 dimensions each for fictional passage texts.
- Two different fictional query texts embedded in query mode each retrieved
  their respective passages at rank 1: 2/2 asymmetric retrieval sanity checks.
- NVIDIA nemotron-3.5-rerank-8b succeeded at its separate reranking endpoint,
  preferring the matching fictional document over an unrelated passage.
- The official E2E runner-only model configuration now selects the verified
  nemotron-3-embed-1b for both ingest and query to avoid mismatched vectors.

These tests do not prove full semantic compilation, production retrieval
accuracy, tenant isolation at scale, or official agent SQL correctness.
Only synthetic examples were transmitted, and API keys/vector payloads
were not logged. The official semantic-compiler run has separate evidence.
