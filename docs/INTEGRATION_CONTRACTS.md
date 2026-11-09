# Integration contracts: bridged repositories

`khs0927/Ontology-platform` is the main monorepo. Four repositories were **merged** with git subtree
(history kept): ArchOntos → `packages/regulation`, Ontology → `packages/aec`, GOD-CAD →
`packages/cad/god-cad`, plus the Sion core. Five repositories stay **separate** and are connected only
through the contracts below. They have their own runtimes (.NET 10 / AutoCAD 2027, Node),
release cycles or licences, and merging them would add a CAD-host toolchain to this repo.

| Repository | Language / host | Relationship | Contract(s) |
|---|---|---|---|
| [power-cad-mcp](https://github.com/khs0927/power-cad-mcp) | C# .NET, AutoCAD 2027 plug-in + MCP server | **calls** the AEC REST API and the Sion API, read-only; produces execution receipts | `aec-operational-rest` (OpenAPI), `sion-aec-query-response`, `power-cad-execution-receipt/1` |
| [hs-steel-cad](https://github.com/khs0927/hs-steel-cad) | C# .NET, MCP | hands steel draw plans, section catalogs and its asset registry to power-cad; section catalogs are also read by Sion's AEC knowledge graph | `hs-steel-draw-plan/1`, `hs-steel-section-catalog/1`, `hs-steel-asset-registry/1` |
| [korean-land-mcp](https://github.com/khs0927/korean-land-mcp) | TypeScript, MCP (V-World) | parcel/zoning records feed regulation facts | `korean-land-parcel-analysis/2` |
| [All-In-Cad](https://github.com/khs0927/All-In-Cad) | Python + C# native hosts | cross-lane DXF verification | `all-in-cad-dxf-evidence` |
| [CAD-MCP](https://github.com/khs0927/CAD-MCP) | evaluation framework (ZWCAD MCP providers) | routing guidance and a DXF fixture; no runtime contract | (fixture only) |
| [building-regulation-gateway](https://github.com/khs0927/building-regulation-gateway) | Python, FastAPI (MCP client) | evidence-only compliance reports are advisory evidence; Sion project workspace adapter | `building-regulation-report/1` |
| [inspection-supervision-mcp](https://github.com/khs0927/inspection-supervision-mcp) | MCP (Kordoc document parsing) | located document excerpts are evidence for one project; **draft / not pinned** (§10) | `kordoc-evidence/1` |

Machine-readable schemas (JSON Schema draft 2020-12) ship in the wheel under
`sion_core/contracts/schemas/` (`packages/core/sion_core/contracts/`). Python access:

```python
from sion_core import contracts
contracts.names()                      # 10 contract names (including 1 unpinned draft)
contracts.is_pinned("kordoc-evidence/1")   # False: draft, no upstream commit pinned (DRAFT_CONTRACTS)
contracts.load("power-cad-execution-receipt/1")
contracts.errors("hs-steel-draw-plan/1", payload)   # [] when valid (needs jsonschema: [test]/[dev] extra)
```

Contract tests: `tests/test_integration_contracts.py`. Upstream files used as fixtures are
copied verbatim into `tests/contracts/fixtures/` with their source commit
([PROVENANCE.md](../tests/contracts/fixtures/PROVENANCE.md)).

## Pinned upstream revisions

The contracts were derived from these commits (read-only clones; no upstream repository was changed):

| Repository | Commit | Date (KST) |
|---|---|---|
| power-cad-mcp | `461df6c` (PR #49) | 2026-10-09 12:11 |
| hs-steel-cad | `cefd395` (PR #8) | 2026-10-09 12:11 |
| korean-land-mcp | `9bca5ea` (PR #2, deps only) | 2026-10-08 20:20 |
| All-In-Cad | `329f9ad` | 2026-10-03 20:39 |
| CAD-MCP | `50ae134` | 2026-10-03 20:15 |
| Ontology (`aec-cair-snapshot/1`, §11) | `d81598f` (PR #100) | 2026-10-17 |

When an upstream changes one of the files named below, update the schema and the pin in this table
and the test module docstring in the same PR.

Not pinned: `kordoc-evidence/1` (khs0927/inspection-supervision-mcp). Its producer side is an open draft
(PR #3) that could not be checked from here, so the table has no row for it. Code marks it with
`contracts.DRAFT_CONTRACTS` / `contracts.is_pinned()`, and the schema with `x-sion-contract.pinned=false`.

### Upstream changes reviewed at the 2026-10-09 pin

| Repository | Change since the previous pin | Contract effect |
|---|---|---|
| power-cad-mcp | PRs #45–#49, #51: asset pipeline (embedding search, atomic `hs_assets.sqlite` swap), headless DXF recover, `cad_hs_*` gateway reply detach, hs-steel marks in `cad_hs_members_place`, docs. `OntologyRestTools.cs` only gains an injectable `TimeProvider` for per-request deadlines | None: request paths, parameters, bounds and timeout settings are unchanged; `OntologyContext.cs`, `OntologyLocate.cs`, `OntologyBlockCandidates.cs` and `ExecutionReceiptContract.cs` are unchanged and no MCP tool exposes the receipt projector yet |
| hs-steel-cad | PR #8: `tools/AssetExtract` (ACadSharp DWG → Drive DB cards), consolidated TODO | None: `DrawPlan.cs`, `SectionCatalogHandoff.cs` and `assets/registry/` are unchanged |
| korean-land-mcp | PR #2: npm audit fixes (vitest 4.1.11, transitive bumps) | None (`analyze_parcel.ts` unchanged) |
| HS-CAD | PR #158: removed a committed API key from `opencode.json`, Pillow ≥ 12.3 | None (scan export and `command_validator.py` unchanged) |
| All-In-Cad, CAD-MCP | no new commits | none |

### Upstream changes reviewed at the 2026-10-08 evening pin

| Repository | Change since the previous pin | Contract effect |
|---|---|---|
| power-cad-mcp | `cad_create_many` (≤5000 entities, one verified transaction) with `layers`, `text_styles`, `dim_styles` (`based_on, text_style, text_height, arrow_size, scale, decimals, text_gap`) and `blocks` (`{name, path?}`, defined from DWG when missing); XData write via per-entity `hs` tags, `cad_xdata_get` and the `cad_query` `xdata` filter; stable `document_id` keyed by the database `FingerprintGuid` (`f2a8469`); PR #43: 10 asset tools `cad_hs_registry_status`, `cad_hs_assets`, `cad_hs_asset_get`, `cad_hs_section_info`, `cad_hs_styles_apply`, `cad_hs_block_place`, `cad_hs_section_draw`, `cad_hs_grid`, `cad_hs_members_place`, `cad_hs_member_list` (65 MCP tools in total) | None on §1–§3: `OntologyRestTools.cs`, `OntologyContext.cs`, `OntologyLocate.cs`, `OntologyBlockCandidates.cs` and `ExecutionReceiptContract.cs` are unchanged. The new tools are host-side mutations or host-side reads; Sion calls none of them. `cad_hs_steel_prepare` now reports `xdata_write_supported=true` (path `cad_create_many`) |
| hs-steel-cad | Project standard options `boltLengthTable`, `holeRule`, `markScheme`, `markFormat`, bolt add length by bolt type, 3-digit marks (`markDigits`), embed head `EB`; `DrawPlan` text/dimension specs carry `style: "HS-KOR"`; PR #7: asset registry `hs-steel-asset-registry/1` (819 assets, JSON Schema, generator `tools/AssetRegistry`) | `hs-steel-draw-plan/1` unchanged (specs stay open objects, so `style` validates). New: `hs-steel-section-catalog/1` (§4a, already read by `packages/aec`) and `hs-steel-asset-registry/1` (§4b) |
| korean-land-mcp | CI workflow (typecheck + vitest) | none (`analyze_parcel.ts` unchanged) |
| HS-CAD | PyRx placeholder readiness report (`pyrx_adapter.py`) | none (scan export and `command_validator.py` unchanged) |
| All-In-Cad, CAD-MCP | no new commits | none |

## Shared rules

1. **Sion is read-only towards CAD hosts.** No Sion route executes a CAD plan or command
   (`test_sion_api_exposes_no_cad_mutation_route`). Mutations stay in the host tools with their own
   approval, document binding and transaction checks.
2. **Advisory, never canonical.** Data from a bridged repo enters Sion as evidence or as facts on a
   request. It does not overwrite canonical entities. Responses Sion gives to CAD tools say so
   explicitly (`canonical: false`, `read_only: true`).
3. **Fail closed.** Missing or unverifiable inputs lead to REVIEW / refusal, not to a guessed value.
4. **Digests are opaque across languages** unless a canonical form is specified. `receipt_digest`
   (power-cad) is computed over `System.Text.Json` output and Sion does not recompute it.

---

## 1. power-cad-mcp → AEC operational REST API (`/v1/*`)

Producer: `aec_intelligence.operational.api` (`packages/aec`, `aec-mcp-http`/uvicorn).
Consumer: `dotnet/PowerCad.Server/OntologyRestTools.cs`, `OntologyLocate.cs`, `OntologyBlockCandidates.cs`
(MCP tools `ontology_catalog`, `ontology_find_elements`, `ontology_blocks`, `ontology_drawings`,
`ontology_element_context`, `ontology_search`, `ontology_ask`, `ontology_auto_context`, `ontology_locate`,
`ontology_block_candidates`; all `ReadOnly=true, Destructive=false`).

Configuration on the power-cad side: `POWERCAD_ONTOLOGY_URL`, bearer token, `POWERCAD_ONTOLOGY_TIMEOUT`,
`POWERCAD_ONTOLOGY_ASK_TIMEOUT` (5–600 s, default 120). The API enforces the bearer token when
`AEC_API_TOKEN` is set (`BearerTokenMiddleware`).

| Request power-cad sends | Accepted by the API |
|---|---|
| `GET /v1/catalog?project_id` | yes |
| `GET /v1/elements` `kind, project_id, storey, text, drawing_category, layer, block_name, bbox, include_properties, limit, cursor` | yes (also `document_id`, `state`) |
| `GET /v1/blocks` `project_id, name_like, limit, cursor` | yes |
| `GET /v1/drawings` `project_id, category, limit, cursor` | yes |
| `GET /v1/elements/{object_id}/context?hops` (power-cad clamps 1–2) | yes (`limit` too) |
| `POST /v1/search` `{query, top_k 1–100, kind?, storey?, project_id?, model?}` | yes; `model` (embedding-model hint) must equal the index's `AEC_EMBEDDING_MODEL` (case-insensitive) or the request gets **422** with the expected name; omitting it is unchanged |
| `POST /v1/ask` `{question 1–2000 chars, project?, top_k 1–30, generate}` | yes; bounds identical to `AskRequest` |

`/v1/ask` returns the GraphRAG object unchanged (answer, route, citations, refusal, warnings). A valid
refusal is a 200 response, separate from transport or auth errors. Cited `object_ids` are hints:
power-cad must locate and verify them in the live drawing before any edit.

Test: `test_aec_operational_api_serves_every_power_cad_request_shape` compares this table with the
API's generated OpenAPI document.

## 2. power-cad-mcp → Sion API `GET /api/v1/aec/query`

Consumer: `SionAecClient.QueryGlobalMemoryAsync` (`OntologyContext.cs`, tool `cad_context_query`).
Config: `POWER_CAD_SION_URL` (absolute http(s), no credentials in the URL), `POWER_CAD_SION_TOKEN`
(required for non-loopback URLs), `POWER_CAD_SION_TIMEOUT` 1–120 s.

Request: `GET /api/v1/aec/query?question=…&top_k=…&project_id=…` with `Authorization: Bearer …`
(Sion scope `read:aec`). Sion accepts `question` 1–2000 chars, `top_k` 0–100, `project_id` ≤ 200 chars.

Response (contract `sion-aec-query-response`):

```json
{"source": "khs0927/Ontology", "canonical": false, "read_only": true, "result": {"…": "…"}}
```

power-cad refuses the body (`[SION_CONTRACT]`) unless `canonical` is the JSON boolean `false` and
`read_only` the JSON boolean `true`; strings like `"false"` or numbers are rejected. It then uses only
`result`. 503 = federation not configured, 502 = CAIR error.

Test: `test_sion_aec_query_satisfies_power_cad_refusal_rules`.

## 3. power-cad-mcp execution receipt → Sion evidence (`power-cad-execution-receipt/1`)

Producer: `ExecutionReceiptContract.Project(plan)` (`ExecutionReceiptContract.cs`, documented in
`docs/framework/EXECUTION_RECEIPT_CONTRACT.md`). At `f2a8469` the projector exists but no MCP tool exposes
it yet (still true at `461df6c`). Schema: `power-cad-execution-receipt-1.schema.json`.

| Status | Meaning | Constraints the schema enforces |
|---|---|---|
| `COMMITTED` | committed non-dry-run result whose executor/plan/document (and source binding) match | `plan_state=Committed`, `committed=true`, `reasons=[]`, `executor_result_digest` present |
| `ROLLED_BACK` | failed, `rollback_verified=true` | `plan_state=Failed`, replacement plan allowed |
| `REJECTED` | failed, `mutation_started=false` proven | `rollback_verified=false`, replacement plan allowed |
| `INDETERMINATE` | anything that cannot be proven (incl. a persisted `Executing` state) | `committed=false`, `requires_manual_reconciliation=true`, `safe_to_create_replacement_plan=false` |

Always: `executor="power-cad"`, `auto_retry_allowed=false`, `canonical_mutation=false`,
`evidence_only=true`, `plan_terminal = (plan_state != "Executing")`. Source binding fields
(`source_binding_handoff_digest`, `source_id`, `source_byte_revision_id`, `parser_revision_id`) are copied
from the plan's `source_binding`.

`document_id` is opaque. Since `f2a8469` the plug-in keys it by the drawing database's `FingerprintGuid`, so
it stays the same for one open drawing across calls within a plug-in session; it is not a cross-session or
cross-machine file identity, and Sion must not join receipts on it beyond that.

Sion handling: store as evidence only. Never retry a plan based on a receipt, never promote a receipt to
canonical CAD state, and treat `receipt_digest` as an opaque identifier.

Tests: four valid statuses, the Executing case, and 12 tampered payloads that must fail.

## 4. hs-steel-cad → power-cad-mcp (`hs-steel-draw-plan/1`)

Producer: `DrawPlan.ToPowerCadHandoff()` (`src/HsSteel.Drafting/DrawPlan.cs`), MCP tool
`hs_draw_plan_handoff`. Consumer: power-cad-mcp (`cad_hs_steel_prepare`). Sion is not part of this
exchange; the schema is kept here so Sion can store a handoff as provenance and check it.

- `schema`, `producer="khs0927/hs-steel-cad"`, `units="mm"`, `scale`, `title`, `meta`
- `entities[]`: `{spec, tag}`. `spec` is a strict Power CAD create spec (`type` ∈ arc, circle, dimension,
  insert, leader, line, polyline, text) and must not carry the HS-STEEL tag (`hs`). `tag` (object or null)
  is kept for XData persistence.
- `execution_authorized=false`, `may_execute_mutation=false`, `requires_live_document_binding=true`,
  `tags_require_xdata_persistence=true`
- `contract_digest`: lowercase hex SHA-256 of the payload without `contract_digest`, serialized as
  canonical JSON (keys sorted ordinally, no whitespace). The test mirrors this for ASCII strings and
  integral numbers. Byte equality with the .NET output for non-ASCII text has not been checked;
  `System.Text.Json` escapes non-ASCII characters.

## 4a. hs-steel-cad section catalog → power-cad-mcp and Sion AEC (`hs-steel-section-catalog/1`)

Producer: `SectionCatalogHandoff.Build` (`src/HsSteel.Assets/SectionCatalogHandoff.cs`). Consumers:
power-cad `cad_hs_steel_catalog_prepare` (`HsSteelTools.PrepareCatalog`) and Sion
`aec_intelligence.operational.graphrag.integrations.load_section_handoffs` (`packages/aec`), which turns
rows into read-only steel section evidence keyed by `canonical_section`. Schema:
`hs-steel-section-catalog-1.schema.json`.

- `validation_status="PASS"`, `capability_scope="single_family_file"`, `global_legacy_catalog_verified=false`,
  `quarantined_rows=0`, `execution_authorized=false`, `may_execute_mutation=false`
- `source_sha256` (lowercase hex SHA-256 of the family file) is required; the Sion loader ignores files
  without it or without PASS, and the schema rejects the same payloads
- `rows[]` (≤500): `spec`, `shape`, `family` non-blank, `dimensions_mm` exactly six non-negative numbers,
  `unit_weight_kg_m`, `paint_area_m2_m`, `aci_color` (integer) — all seven are required per row
- `contract_digest`: same canonical-JSON SHA-256 rule as §4. Row-count consistency
  (`returned_rows == len(rows)`, `accepted_rows ≤ read_rows`) is checked by power-cad, not by the schema.

Tests: a valid synthetic handoff goes through the real AEC loader; 11 tampered payloads fail, and rows
missing (or renaming) a required field such as `aci_color` fail.

## 4b. hs-steel-cad asset registry (`hs-steel-asset-registry/1`)

Producer: `tools/AssetRegistry` → `assets/registry/asset-registry.json` (819 assets: 761 licensed legacy
files referenced by path and hash, 58 code-defined standards such as layers, HS-KOR text/dim styles and the
project standard options). Consumer: power-cad `HsSteelRegistry` and the `cad_hs_*` tools
(`HS_STEEL_ASSET_ROOT`). The schema is the upstream `asset-registry.schema.json`, copied verbatim
(`hs-steel-asset-registry-1.schema.json`, sha256 recorded in PROVENANCE.md).

**Sion does not ingest the registry.** As with §4, the schema is kept so a registry snapshot can be stored
as provenance for a steel drawing and checked. `loadedBy` entries name host tools; they are references,
never grants, and Sion does not call them. The legacy files themselves are licensed and never enter this
repo. Tests validate a trimmed copy of the real registry (one asset per category plus both
`standard-option` rows) and 9 drift cases.

## 5. korean-land-mcp → regulation facts (`korean-land-parcel-analysis/2`)

Producer: MCP tool `analyze_parcel(query)` (`src/tools/analyze_parcel.ts`, v2.0, V-World backed). The
record is returned as JSON text in the MCP content. `undefined` members are dropped by `JSON.stringify`,
so many parcel fields are optional.

Consumer: `sion_api.regulation.facts_from_land_parcel(record)` and
`POST /api/v1/regulation/evaluate` with `{"rule": …, "land_parcel": <record>, "facts": {…}}`.
Fact precedence: entity properties < `land.*` < explicit `facts`. The response echoes the derived
`land` object. An invalid record returns 422.

Derived facts (`land.*`), all copied, none inferred:

| Fact | From |
|---|---|
| `pnu`, `jibun`, `jimok`, `jimok_code`, `is_mountain_register`, `address`, `sido`, `sigg`, `emd_dong` | `parcel` (null/absent → no fact) |
| `use_zone` (first named 용도지역), `use_zones`, `has_use_zone_hit` | `zoning.use_zone` (`(unnamed)` is never used) |
| `has_use_district`, `use_districts` | `zoning.use_district` |
| `has_use_area`, `use_areas`, `in_development_restriction_zone` (layer `LT_C_UD801`) | `zoning.use_area` |
| `land_transaction_permit` | `zoning.land_transaction_permit` |
| `in_district_plan`, `district_plan_names` | `district_plan` |
| `urban_facility_overlap` | `urban_facility` |
| `has_other_law_designation`, `other_law_names`, `priority_delegation` | `other_law_designations`, `priority_delegation_hint` |
| `buildings_present`, `building_count` | `buildings` |
| `precision`, `layer_error_count`, `unverified`, `contract` | `source`, `layer_errors` |

**Fail-closed rule.** A hit is always a fact. A *negative* (false or empty) is a fact only when the
overlays were matched against the parcel polygon (`source.precision == "polygon"`) and that layer
family reported no `layer_errors`. Otherwise the fact is omitted and listed in `land.unverified`, so an
ArchOntos rule that needs it evaluates to **REVIEW**. Layer families follow the layer-id groups in
`analyze_parcel.ts`. An error on an unknown layer makes every negative unverified.

V-World data has no legal force (the record's `disclaimer`). Regulation outcomes based on it are advisory.

## 6. All-In-Cad ↔ Sion DXF census (`all-in-cad-dxf-evidence`)

All-In-Cad `inspect_dxf` (`src/all_in_cad/dxf_evidence.py`) runs `ezdxf.recover` and returns
`DxfEvidence{path, entity_count, layer_counts, entities[{handle, dxftype, layer}], auditor_has_errors}`.
Sion's `sion_cad.reader.dxf_census(path)` returns the same shape plus `parser` and `warnings`, so the
two headless lanes can be cross-checked:

- ezdxf path: opened with `open_dxf` (strict → recover, CP949 re-read), then audited like `recover`.
  Handles and types match All-In-Cad entity for entity on all 11 test drawings, including the CAD-MCP
  fixture and the 9 Korean drawings. Layer names also match, except where Sion re-read CP949.
- Audit fixes that remove entities are reported (`audit fix: …` warnings). Example: the CAD-MCP fixture
  `arch_sample_room.dxf` has two `DIMENSION`s without a geometry block. ezdxf/All-In-Cad drop them (9
  entities), while the file contains 11.
- Built-in parser (no ezdxf): same shape, `auditor_has_errors=null` (no audit claim), file order, and a
  superset of the audited entities.

All-In-Cad's native protocol (`aic.native/1`, length-prefixed JSON over a current-user named pipe,
signed approval tokens, write leases) is host-side. Sion does not speak it.

## 7. HS-CAD (retired)

HS-CAD is no longer an active bridge. `power-cad-mcp` is the only active CAD host bridge.
Its contracts (`hs-cad-scan-objects`, `hs-cad-command`), schemas, fixtures and tests
were retired in the integration following PR #100. Historical HS-CAD rows in the
upstream review section remain as provenance, not active integrations.

## 8. CAD-MCP

CAD-MCP evaluates ZWCAD MCP providers and recommends a **thin router** (single writer, tool discovery)
rather than a monolithic CAD MCP. Its README marks historical scores as unverified
(`LEGACY_SYNTHETIC`). **Sion does not ingest CAD-MCP results as evidence.** Its generated fixture
`fixtures/arch_sample_room.dxf` is vendored for the DXF census tests. The routing guidance matches how
this repo reaches CAD hosts: through read-only adapters (CAIR, `/api/v1/aec/query`), never through
several concurrent writers.

## 9. building-regulation-gateway → regulation evidence (`building-regulation-report/1`)

Producer: `khs0927/building-regulation-gateway` @ `21e146574c2ba173ed436c685b376f5cefa813b0` (v0.2). Seven REST/MCP tools collect site, spatial, building, law, interpretation, technical and document evidence. Default decisions remain evidence-only; explicitly configured reviewed rules may produce scoped decisions. Incomplete coverage and unresolved conflicts fail closed.

Sion provides an authenticated HTTP bridge and a project workspace at `/regulation`. Saved reports are advisory (`canonical:false`), with source evidence and project relationships recorded through existing transactions/outbox. No CAD mutation is performed. Contract schema and tests cover the v0.2 statuses and require review metadata for determinate decisions. See [REGULATION-WORKSPACE.ko.md](REGULATION-WORKSPACE.ko.md) for endpoints, configuration and MCP router adapter.

Gateway runtime remains isolated (its own SQLite or PostgreSQL snapshot store and MCP dependencies). The platform owns project work, notes and tasks in its existing entity/evidence tables. Check service ports per PC; tokens come from process environment.

## 10. inspection-supervision-mcp (Kordoc) → Sion evidence (`kordoc-evidence/1`) — draft / not pinned

Status: **draft / not pinned.** Issue #71 step I. The producer is `khs0927/inspection-supervision-mcp`
(Kordoc document parsing; read-only mobile connection in its draft PR #3). No upstream commit is pinned
and no upstream file is vendored. The schema `kordoc-evidence-1.schema.json` describes what Sion accepts.
It does not mirror producer code. Once the producer ships the shape, pin the commit in the table above,
add captured fixtures with provenance and remove the entry from `contracts.DRAFT_CONTRACTS`, all in one PR.

One payload is one located excerpt of one source document revision:

| Member | Rule |
|---|---|
| `schema`, `producer` | `kordoc-evidence/1`, `khs0927/inspection-supervision-mcp` |
| `project_id` | required, non-blank, ≤ 200 chars. Readers enforce project ACL on it; evidence without a project is rejected |
| `source` | `sha256` (lowercase hex of the file bytes), `document_id`, `document_version` required; `file_name`, `media_type`, `source_uri` optional. `source_uri` is a reference, never a grant to change the original |
| `parser` | `name`, `version` required (e.g. `kordoc` and its version) |
| `locator` | `page` (1-based) required; `table` and `cell {row, col}` (1-based) optional; a `cell` needs a `table` |
| `source_text` | verbatim `quote` and `quote_sha256` (SHA-256 of the UTF-8 quote, checked by `contracts.errors`) |
| `classification.state` | `unverified` (no review metadata allowed), `human_verified` or `rejected` (both need `reviewer_kind="human"`, `reviewed_by`, `reviewed_at`; `rejected` also needs `reason` and no `proposed_claims`) |
| `proposed_claims[]` | producer interpretations: `claim_id` (unique), `statement`, optional `subject/predicate/object`, `claim_state="candidate"`, `canonical=false`. No quote inside a claim |
| `canonical`, `evidence_only` | always `false`, `true`. Unknown top-level members (e.g. `canonical_claims`) are rejected |

**Quoted text vs. canonical claims.** `source_text` is what the document says at the locator.
`proposed_claims` are someone's reading of it. Both stay evidence. Sion canonical claims are created only
through Sion's own review flow, never from this payload. `human_verified` means a person checked the
excerpt against the source revision. It does not approve a claim. Machine-assigned verification is
rejected (`reviewer_kind` must be `human`), and Sion never auto-approves candidates from this payload.

Tests: `tests/contracts/fixtures/kordoc-evidence/` holds synthetic valid (3) and invalid (23) payloads,
each invalid file breaking one rule (see PROVENANCE.md). Parametrized tests also drop every top-level
and nested required field (`source`, `parser`, `locator`, `source_text`, `classification`), cover locator
variants (page, page+table, page+table+cell; cell without table, zero indexes and unknown keys fail) and
reject payloads that mark source text or claims as canonical.

## 11. khs0927/Ontology ingestion → Sion graph + evidence (`aec-cair-snapshot/1`)

Consolidation phase 1 ([CONSOLIDATION_PLAN.md](CONSOLIDATION_PLAN.md)). Producer: Ontology's own CLI
(`aec ingest-dxf`, `aec ingest-file` for IFC) writing `projects/<id>/03_CAIR/project-cair.json`
(`CAIRSnapshot.to_dict()`, `schema_version` 0.x). Consumer: `sion_cair.ingest`
(`run_ontology_ingest`, `cair_snapshot_to_map_export`, `ingest_cair_snapshot`, `ingest_with_ontology`).

| Ontology runtime | How to select it |
|---|---|
| bundled subtree `packages/aec` (default) | `ontology_root=None` or `"bundled"` |
| external checkout (local path, e.g. `C:\CODE\Ontology`) | `ontology_root="C:\CODE\Ontology"` (its `src` goes on `PYTHONPATH` of the subprocess) |
| pinned install in a separate venv | `python="C:\venvs\aec\Scripts\python.exe"` after `pip install "aec-intelligence[cad,bim] @ git+https://github.com/khs0927/Ontology@d81598f"` |

Ontology always runs in a **subprocess** against a temporary repository root, so two copies of the
`aec_intelligence` import package never share an interpreter. Mapping: one `Artifact` node per source
file (key = source SHA-256, `external_uri=urn:sha256:…`), one `Concept` node per CAIR object
(key `cair:<CAIR id>`), `EXTRACTED_FROM` object → artifact with the classification confidence and one
evidence row (`extractor=aec-cair/<parser>`, locator = `geometry_ref`). Object↔object relations map to
`PART_OF` (`hostedBy`, `containedIn`; IFC `contains` reversed), `CONNECTS_TO`, `REFERENCES`,
`DERIVED_FROM`, else `RELATED_TO` with `properties.cair_predicate`. `containsElement` is not imported.
Everything is `unverified`; import is idempotent. A snapshot with `status=FAILED` or a missing
`schema_version`/`objects`/`source` is refused (`AecCairError`).

Install: `pip install -e '.[aec]'` (= `cad` + `bim`). Fixtures: `tests/contracts/fixtures/aec-cair/`
(captured from Ontology @ `d81598f`, see PROVENANCE.md). Tests: `tests/test_aec_cair_ingest_contract.py`.

## In-repo contracts (for reference)

- `aec-facts-export/1`: `GET /v1/kg/projects/{project_key}/facts` (packages/aec) exports rule facts and
  ArchOntos subject references for one project.
- `GET /api/v1/contracts`: Sion's read-only catalogue of project contracts from khs0927/All-in-memory.
- `POST /api/v1/analyze/dxf`: GOD-CAD `Drawing` contract (see `packages/README.md`).


### v0.2 project workspace integration

Sion `/regulation` provides project-scoped saved reviews, notes, tasks and source-cited Markdown briefings. API: `/api/v1/regulation/gateway/report`, `/api/v1/regulation/works`, `/api/v1/regulation/works/{id}` and `/briefing`. Saves fetch a server-owned gateway audit run and validate the report before creating Document/Evidence/PART_OF rows in one transaction with the existing outbox and Drive export hooks. Reports and evidence remain `canonical:false`, unverified; work completion does not establish legal compliance.

The pinned v0.2 producer supports scoped reviewed-rule decisions in addition to evidence-only outcomes. The schema accepts these statuses and requires review metadata for determinate decisions. Historical applicability, local ordinances, missing rule domains and incomplete spatial coverage remain fail-closed upstream.

See [REGULATION-WORKSPACE.ko.md](REGULATION-WORKSPACE.ko.md) for configuration and the existing AEC MCP router integration.
