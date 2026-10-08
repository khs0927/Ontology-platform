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
| `data/sources/sketchup/object-classes.json` | 30 SketchUp object classes (`sion-sketchup-object-classes/v1`) |
| `data/sources/sketchup/0914-meeting/classification.json` | Definition → class overlay, 214 assignments, all **inferred** (`sion-sketchup-classification/v1`, pinned to the dump sha256) |
| `docs/sketchup/MODELING-GUIDELINES.ko.md` | 31 Korean guideline sections, each with a `sion-guide` metadata comment |
| `packages/ingestion/sion_ingestion/sketchup_assets.py` | Generator, evidence attacher and CLI |
| `data/bootstrap/sketchup-0914-meeting.json` | Generated export: 626 nodes / 2,360 edges (tests regenerate and compare) |
| `scripts/sketchup/*.rb` | The read-only Ruby extraction scripts |

## Graph layout

Nodes use only the 11 core entity types; edges use only core relation types.

| Stable key | Type | Content |
|---|---|---|
| `sketchup:0914-meeting:model` | Artifact | File, version, units, bounds, location, counts |
| `sketchup:0914-meeting:dump` | Dataset | The dump file |
| `sketchup:0914-meeting:def:<slug>` | Concept | One per definition (297): size, counts, tags, materials, first placement, probe facts |
| `sketchup:0914-meeting:obj:<persistent_id>` | Entity | Top-level and second-level placements (76): path, tag, material, transform, world bounds |
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

## How an agent should use it

1. Map the request to a class (`sketchup:class:retaining-wall`, …).
2. `POST /api/v1/graphrag/query` `{"question": "SketchUp 옹벽 그리는 방법과 이 모델의 옹벽 예시", "mode": "mix"}`:
   the class pulls in its guideline chunk (`applies_to_class`) and the classified definitions.
3. Take numbers only from definition/placement nodes (facts), never from the inferred class edge.
4. Follow the `mcp-execution` and `agent-judgement` chunks: read first, one operation per change,
   verify bounds, never save, purge or delete without the user.

## Adding another model

Dump with `scripts/sketchup/dump_model.rb` (+ `geom_probe.rb`), commit the files under
`data/sources/sketchup/<namespace>/`, write a `classification.json` pinned to the new dump sha256,
add a `DEFAULTS["<namespace>"]` entry, run `build`, and add a regeneration test. Guideline
sections can cite `def:<name>`, `obj:<persistent_id>`, `tag:`, `mat:`, `scene:N`, `section:N`,
`model:`; unknown references fail the build.
