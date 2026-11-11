# SketchUp modelling knowledge for GraphRAG

Knowledge assets from the SketchUp model `0914_담당미팅.skp` (sloped site with terraced
parking, retaining walls, a two-storey cafe and an annex) plus Korean modelling guidelines,
in the canonical `sion-map-export/v1` contract. After import and `POST /api/v1/graphrag/project`
an agent can ask GraphRAG how to draw an object class, get the guideline chunk, and get
real examples from this model with sizes, levels, tags, materials and evidence.

## Files

| Path | Role |
|---|---|
| `data/sources/sketchup/0914-meeting/model_dump.json` | Raw read-only dump (evidence, byte-identical, see `data/sources/PROVENANCE.md`) |
| `data/sources/sketchup/0914-meeting/geometry_probe.json` | Face levels, slope angles and arc radii for 95 definitions |
| `data/sources/sketchup/0914-meeting/grouping_probe.json` | Grouping facts: pid path, local transform, mirror, lock, hide and glue for all 619 instances; per-definition raw geometry and child instances by tag, origin position (bbox min) and behaviour |
| `data/sources/sketchup/object-classes.json` | 30 SketchUp object classes (`sion-sketchup-object-classes/v1`) |
| `data/sources/sketchup/0914-meeting/classification.json` | Definition → class overlay, 214 assignments, all **inferred** (`sion-sketchup-classification/v1`, pinned to the dump sha256) |
| `docs/sketchup/MODELING-GUIDELINES.ko.md` | 31 Korean guideline sections, each with a `sion-guide` metadata comment |
| `docs/sketchup/GROUPING-WORKFLOW.ko.md` | How the model was grouped: 11 observed rules (`kind="pattern"`) and a 12-step grouping workflow (`kind="step"`, `implements=` rule ids) |
| `packages/ingestion/sion_ingestion/sketchup_assets.py` | Generator, evidence attacher and CLI |
| `data/sources/sketchup/namespaces.json` | Namespace registry (`sion-sketchup-namespaces/v1`): repo-relative build inputs/output per model; `sketchup_assets.DEFAULTS` is loaded from it |
| `data/sources/sketchup/0914-meeting/manifest.json` | Collection manifest (`sion-sketchup-collection-manifest/v1`, `schemas/sion-sketchup-collection-manifest-1.schema.json`): model, SketchUp version, capture SHA-256, inputs, outputs |
| `packages/ingestion/sion_ingestion/sketchup_collection.py` | `preflight`, `manifest` and `scaffold` commands for collecting further models |
| `data/bootstrap/sketchup-0914-meeting.json` | Generated export: 1,195 nodes / 4,509 edges (tests regenerate and compare) |
| `scripts/sketchup/*.rb` | The read-only Ruby extraction scripts |
| `docs/sketchup/AGENT-PLAYBOOK.ko.md` | 에이전트가 GraphRAG를 조회하고 SketchUp 작업으로 옮기는 실행 플레이북 |

## Graph layout

Nodes use only the 11 core entity types; edges use only core relation types.

| Stable key | Type | Content |
|---|---|---|
| `sketchup:0914-meeting:model` | Artifact | File, version, units, bounds, location, counts |
| `sketchup:0914-meeting:dump` | Dataset | The dump file |
| `sketchup:0914-meeting:def:<slug>` | Concept | One per definition (297): size, counts, tags, materials, first placement, probe facts |
| `sketchup:0914-meeting:obj:<persistent_id>` | Entity | Top-level and second-level placements (76): path, tag, material, transform, world bounds |
| `sketchup:0914-meeting:occ:<pid.pid.…>` | Entity | Deeper placements (543, depth 2–6), keyed by the persistent-id path from the root because deep ids repeat across copies |
| `sketchup:0914-meeting:grouping-probe` | Dataset | The grouping probe file |
| `sketchup:workflow:grouping` | Workflow | The 12-step grouping workflow (`step_order`) |
| `sketchup:grouping:step:<id>` | Workflow | One step: inputs, decision rules, grouping/naming/tagging operation, MCP/Ruby (mm), checks, evidence; `step_no`, `previous_step`, `next_step` |
| `sketchup:grouping:pattern:<id>` | Decision | One observed grouping rule ([관측]/[추론]/[권장]) |
| `sketchup:grouping:doc:<id>` | Document | Grouping overview and statistics |
| `sketchup:0914-meeting:tag:<slug>` / `mat:` / `style:` / `scene:N` / `section:N` | Concept | 49 tags (`@wall` → `at-wall`), 130 materials, 3 styles, 3 scenes, 1 section plane |
| `sketchup:class:<id>` | Concept | 30 object classes (`retaining-wall`, `curtain-wall`, `furniture`, …) |
| `sketchup:guide:<id>` | Document | 31 Korean guideline chunks (the full section text is the description) |
| `sketchup:workflow:architectural-site-model` | Workflow | Ordered guideline steps |
| `tool:sketchup`, `tool:mcp:sketchup-mcp2`, `tool:mcp:hueflow-sketchup` | Tool | Execution tools |

| Edge (predicate) | Relation | State |
|---|---|---|
| definition/tag/material/style/scene/section → model; child definition → parent definition (`nested_in_definition`, `count`); placement → model (`placed_in`) or parent placement (`nested_in_instance`) | `PART_OF` | `machine_verified`, `source_kind=mcp`, confidence 1.0 |
| definition → tag (`uses_tag`), → material (`uses_material`); placement → tag (`placed_on_tag`), → material (`painted_with_material`); scene → style (`uses_style`); model → `tool:sketchup` (`authored_in`) | `USES` | `machine_verified` |
| placement → definition (`instance_of`); scene → hidden tag | `REFERENCES` | `machine_verified` |
| dump → model (`extracted_from`); dump → `tool:mcp:hueflow-sketchup` (`extracted_via_mcp`) | `EXTRACTED_FROM` / `DERIVED_FROM` | `machine_verified` |
| unreachable definition → `unused-definition` (`classified_as`) | `IMPLEMENTS` | `machine_verified` (graph reachability) |
| definition → class (`classified_as`, with `basis_ko`) | `IMPLEMENTS` | **`unverified` candidate** |
| guide → workflow (`step_of_workflow`), → earlier guide (`after_step`); workflow → model (`derived_from_model`) | `PART_OF` / `DEPENDS_ON` / `DERIVED_FROM` | candidate |
| guide → class (`applies_to_class`) | `REFERENCES` | candidate |
| guide → tool (`executed_with_tool`, `tool_names`) | `USES` | candidate |
| guide → cited definition/placement/tag/material/scene (`cites_model_evidence`) | `DERIVED_FROM` | candidate |
| grouping step → workflow (`step_of_workflow`, `order`); step → previous step (`follows_step`); previous → next (`precedes`) | `PART_OF` / `DEPENDS_ON` / `RELATED_TO` | candidate |
| grouping step → rule (`applies_rule`); rule → workflow (`rule_of_workflow`) | `IMPLEMENTS` / `SUPPORTS` | candidate |
| grouping chunk → class / tool / cited object (`occ:` paths allowed) | `REFERENCES` / `USES` / `DERIVED_FROM` | candidate |
| grouping workflow → modelling workflow (`sub_workflow_of_modeling`), → `guide:group-component` (`expands_guideline`), → model / grouping probe | `RELATED_TO` / `REFERENCES` / `DERIVED_FROM` | candidate |
| grouping probe → model (`extracted_from`), → `tool:mcp:hueflow-sketchup` (`extracted_via_mcp`) | `EXTRACTED_FROM` / `DERIVED_FROM` | `machine_verified` |

Placement nodes also carry `properties.grouping` (local identity, local origin, mirrored, locked,
hidden, glued_to). Definition nodes carry `properties.grouping` (role `container`/`leaf`/`mixed`,
raw geometry and child instances by tag, bbox min, insertion point, behaviour such as `cuts_opening`).

Every node except the three tools and every edge carry `properties.su_evidence`
(`source_file` relative to the repo, `source_sha256`, `locator` such as `$.definitions[12]`
or `L240-L262 #column-beam`).

## Ingest

```bash
# keeps machine_verified facts, imports inferences as review candidates,
# and writes one evidence row per node/edge (source_uri @ locator)
uv run python -m sion_ingestion.sketchup_assets import --database-url "$SION_DATABASE_URL"
# then project into LightRAG
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/graphrag/project
```

The generic `sion-relations import data/bootstrap/sketchup-0914-meeting.json` also works, but
the converter treats every edge as an unverified candidate and replaces `properties.provenance`;
`su_evidence` stays in the properties.

Candidates (`properties.candidate = true`: the 214 classifications and the guideline links) show
up at `/review` and stay `unverified` until a person approves them.

### Reviewing them quickly (`/review`)

Opening the page, picking a queue, or changing a filter never writes a decision. The `추천`
badge stays display-only. A decision is recorded only when a person uses 승인/거절, the `a`/`r`
keys, or 선택 일괄 승인/거절 on rows they checked.

- Queue chips (counts follow the status filter): **맵 관계** (issue #3), **SketchUp 분류**
  (`predicate=classified_as`, the 214 assignments), **워크플로** (queued candidates whose predicate
  is a guideline or grouping link), **기타** (level, block, and other inferred candidates). The chip
  also sets a reading group (type, 도착 노드, or 출발 노드) and does not select rows. The importer
  still queues only inferred or imported candidates, so `source_kind=document` links stay out of
  this page.
- Each card shows `basis_ko` inline. Map edges, which have no `basis_ko`, show the source and
  target descriptions and the first evidence excerpt. The rest of the excerpts stay under
  **노드 설명 · 근거 원문**.
- Filter by relation type, source file, evidence count, confidence minimum and maximum (bands:
  0.8 이상, 0.6–0.7, 0.5 이하, 미기재), `추천`, or text. Group by type, source file, hint,
  **출발 노드**, or **도착 노드**.
- Tick rows, a group, or `필터 결과 전체 선택`, then `선택 일괄 승인/거절`. `한 건씩` (also the
  phone default) shows one card with a bottom 승인/거절 bar. Keyboard: `j`/`k` move, `n`/`p`
  next/previous pending, `x` select, `a` approve, `r` reject, `f` toggle one-card mode.
  The progress bar is pending/approved/rejected plus how many decisions this page recorded.
- `선택 일괄 승인/거절` calls `POST /api/v1/relations/candidates/bulk`
  `{"ids": [...], "decision": "approve"|"reject", "note": "<required>", "reviewer": "..."}`
  (`write:knowledge`). Only the listed ids are touched; each gets the same `properties.review`
  record and evidence-row copy as the per-item route plus a shared `batch_id`. The response has a
  per-id `result` (`applied`, `unchanged` on repeat, `conflict` if the opposite decision exists,
  `not_found`, `not_candidate`, `invalid_id`), so retries are safe.
- Safe writes (#71): every candidate carries a `version` (bumped by each approve/reject/reopen).
  Per-item routes accept `expected_version` and answer `409` with
  `{"error": "version_conflict", "current_version": n, ...}` when someone changed it first; bulk
  accepts `expected_versions: {id: n}` and reports a per-id `conflict` with the current `version`.
  Without it the old behaviour is kept unless `SION_REVIEW_REQUIRE_VERSION=1` (then `428`).
  `dry_run: true` (per-item, bulk, reopen) returns the exact would-be result and writes nothing
  (the `미리보기만` checkbox on the page). Inferred co-occurrence-only edges (or `trust: low` / `low_trust`)
  are flagged `low_trust` and need `confirm_low_trust: true` to be approved (`422` otherwise).
  `GET /api/v1/relations/candidates/{id}/audit` returns the append-only decision log
  (`properties.review_log`: action, reviewer, note, batch_id, prior/new state, from/to version,
  time) and whether replaying it reproduces the stored state.
- The page is usable on a phone (single-column controls, 44px buttons) and shows each
  candidate's source locator and source `sha256` when the import recorded them.
- The `추천` badge (evidence count, confidence, co-occurrence-only rules) is display-only and is
  never applied automatically.
- Approval is a review judgement, **not a fact verification**: confidence and evidence are not
  changed, and an approved class edge is still an inference (take numbers from definition/placement
  facts). The opposite decision is refused (`409` / `conflict`) until the candidate is reopened with
  `POST /api/v1/relations/candidates/{id}/reopen` and a required note; the previous decision
  (reviewer, note, `batch_id`) stays in `properties.review_history` and nothing is deleted.
- `GET /api/v1/review/report` (paged with `limit`/`offset`, optional `batch_id`) lists which reviewed
  relations the review-state policy keeps (rejected ones are excluded by default) and each bulk
  `batch_id` with its per-id results. The live GraphRAG index applies the same default policy
  (`live_index_applies_policy: true`), so rejected relations are not indexed by default.

## How an agent should use it

1. Map the request to a class (`sketchup:class:retaining-wall`, …).
2. `POST /api/v1/graphrag/query` `{"question": "SketchUp 옹벽 그리는 방법과 이 모델의 옹벽 예시", "mode": "mix"}`:
   the class pulls in its guideline chunk (`applies_to_class`) and the classified definitions.
3. Take numbers only from definition/placement nodes (facts), never from the inferred class edge.
4. Follow the `mcp-execution` and `agent-judgement` chunks: read first, one operation per change,
   verify bounds, never save, purge or delete without the user.

## Adding another model

The collection pipeline is in `sion_ingestion.sketchup_collection` (details and the full check list in
`scripts/sketchup/README.md`):

1. Run the read-only scripts (`dump_model.rb`, `geom_probe.rb`, `grouping_probe.rb`, optionally
   `export_objects.rb`) in SketchUp.
2. `python -m sion_ingestion.sketchup_collection scaffold --namespace <ns> --from-dir <export folder>
   --guidelines <model guide>.md`: copies the JSON captures to `data/sources/sketchup/<ns>/`, writes
   an empty `classification.json` pinned to the dump sha256, registers the namespace in
   `data/sources/sketchup/namespaces.json`, runs `build` and `build --check`, writes `manifest.json`
   and emits `tests/test_sketchup_ns_<ns>.py`.
3. Fill `classification.json` (every assignment stays an inferred, `unverified` candidate with a
   `basis_ko`), rebuild with `sketchup_assets build --namespace <ns>`, and extend the test stub with
   spot facts.
4. `python -m sion_ingestion.sketchup_collection preflight --build` before committing; CI runs the same
   preflight through `tests/test_sketchup_collection.py`.

Guideline sections can cite `def:<name>`, `obj:<persistent_id>`, `tag:`, `mat:`, `scene:N`, `section:N`,
`model:`; unknown references fail the build, so a new model needs a guideline document whose evidence
references exist in its own dump. The guideline, workflow and class nodes (`sketchup:guide:*`,
`sketchup:workflow:*`, `sketchup:class:*`) are not namespaced, so two exports built from the same
documents share them on import.
