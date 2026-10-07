# Integration contracts: bridged repositories

`khs0927/Ontology-platform` is the main monorepo. Four repositories were **merged** with git subtree
(history kept): ArchOntos → `packages/regulation`, Ontology → `packages/aec`, GOD-CAD →
`packages/cad/god-cad`, plus the Sion core. Six repositories stay **separate** and are connected only
through the contracts below. They have their own runtimes (.NET 10 / AutoCAD 2027, ZWCAD COM, Node),
release cycles or licences, and merging them would add a CAD-host toolchain to this repo.

| Repository | Language / host | Relationship | Contract(s) |
|---|---|---|---|
| [power-cad-mcp](https://github.com/khs0927/power-cad-mcp) | C# .NET, AutoCAD 2027 plug-in + MCP server | **calls** the AEC REST API and the Sion API, read-only; produces execution receipts | `aec-operational-rest` (OpenAPI), `sion-aec-query-response`, `power-cad-execution-receipt/1` |
| [hs-steel-cad](https://github.com/khs0927/hs-steel-cad) | C# .NET, MCP | hands steel draw plans to power-cad (Sion is not a party) | `hs-steel-draw-plan/1` |
| [korean-land-mcp](https://github.com/khs0927/korean-land-mcp) | TypeScript, MCP (V-World) | parcel/zoning records feed regulation facts | `korean-land-parcel-analysis/2` |
| [HS-CAD](https://github.com/khs0927/HS-CAD) | Python, ZWCAD COM / PyRx | ModelSpace scans are evidence; its command JSON is checked, never executed by Sion | `hs-cad-scan-objects`, `hs-cad-command` |
| [All-In-Cad](https://github.com/khs0927/All-In-Cad) | Python + C# native hosts | cross-lane DXF verification | `all-in-cad-dxf-evidence` |
| [CAD-MCP](https://github.com/khs0927/CAD-MCP) | evaluation framework (ZWCAD MCP providers) | routing guidance and a DXF fixture; no runtime contract | (fixture only) |

Machine-readable schemas (JSON Schema draft 2020-12) ship in the wheel under
`sion_core/contracts/schemas/` (`packages/core/sion_core/contracts/`). Python access:

```python
from sion_core import contracts
contracts.names()                      # the 7 contract names
contracts.load("power-cad-execution-receipt/1")
contracts.errors("hs-steel-draw-plan/1", payload)   # [] when valid (needs jsonschema: [test]/[dev] extra)
```

Contract tests: `tests/test_integration_contracts.py` (58 tests). Upstream files used as fixtures are
copied verbatim into `tests/contracts/fixtures/` with their source commit
([PROVENANCE.md](../tests/contracts/fixtures/PROVENANCE.md)).

## Pinned upstream revisions

The contracts were derived from these commits (read-only clones; no upstream repository was changed):

| Repository | Commit | Date (KST) |
|---|---|---|
| power-cad-mcp | `f2a8469` | 2026-10-08 02:25 |
| hs-steel-cad | `233a4a4` | 2026-10-08 02:24 |
| korean-land-mcp | `ec25b13` | 2026-10-06 14:12 |
| HS-CAD | `45d16b6` | 2026-10-03 19:55 |
| All-In-Cad | `329f9ad` | 2026-10-03 20:39 |
| CAD-MCP | `50ae134` | 2026-10-03 20:15 |

When an upstream changes one of the files named below, update the schema and the pin in this table
and the test module docstring in the same PR.

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
it yet. Schema: `power-cad-execution-receipt-1.schema.json`.

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

The related `hs-steel-section-catalog/1` handoff (validated by power-cad `cad_hs_steel_catalog_prepare`:
`validation_status=PASS`, ≤500 rows, six `dimensions_mm`) is not consumed by Sion and has no schema here.

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

## 7. HS-CAD (`hs-cad-scan-objects`, `hs-cad-command`)

- **Scan export** (`python -m src.main scan … --out objects.json`, `export_objects_json`): a list of
  ModelSpace objects `{handle, entity_type, layer, object_name?, color?, start?, end?, insert?, points?,
  closed?, area?, name?, effective_name?, …}`. Sion may store a scan as evidence about one DWG revision.
  Validated against HS-CAD's own `examples/sample_objects/layer_semantic_sample.json`.
- **Command envelope** (`run-command`): `{command, params, safety}` where `command` is in HS-CAD's
  `ALLOWED_COMMANDS` (26 names) with the same required non-empty params as `command_validator.py`.
  Execution needs `--execute` on HS-CAD's CLI plus backup/preview safety. Sion never sends these. The
  schema lets Sion-side reviewers check an AI proposal before a person runs it. Upstream example
  `capture_screen.json` is **not** accepted (not in `ALLOWED_COMMANDS`).

## 8. CAD-MCP

CAD-MCP evaluates ZWCAD MCP providers and recommends a **thin router** (single writer, tool discovery)
rather than a monolithic CAD MCP. Its README marks historical scores as unverified
(`LEGACY_SYNTHETIC`). **Sion does not ingest CAD-MCP results as evidence.** Its generated fixture
`fixtures/arch_sample_room.dxf` is vendored for the DXF census tests. The routing guidance matches how
this repo reaches CAD hosts: through read-only adapters (CAIR, `/api/v1/aec/query`), never through
several concurrent writers.

## In-repo contracts (for reference)

- `aec-facts-export/1`: `GET /v1/kg/projects/{project_key}/facts` (packages/aec) exports rule facts and
  ArchOntos subject references for one project.
- `GET /api/v1/contracts`: Sion's read-only catalogue of project contracts from khs0927/All-in-memory.
- `POST /api/v1/analyze/dxf`: GOD-CAD `Drawing` contract (see `packages/README.md`).
