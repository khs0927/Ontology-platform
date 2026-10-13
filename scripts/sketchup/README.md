# SketchUp read-only extraction scripts

Ruby scripts that produced `data/sources/sketchup/0914-meeting/*`. They run inside SketchUp
through an MCP server's Ruby tool (`claude:hueflow-sketchup` `execute_ruby`, or
`sketchup-mcp2` `eval_ruby`). **They never modify the model**: no geometry, tag, material,
page or style is created, moved or deleted, and nothing calls `model.save`, `undo` or purge.

| Script | Output | Notes |
|---|---|---|
| `dump_model.rb` | `model_dump.json` | Model info, units, shadow/geo info, styles, scenes + cameras, tags (usage per entity type), materials (texture, usage), all definitions (entity counts, face area, child definitions, tags/materials used, behaviour, attributes), the instance hierarchy (persistent id, path, tag, material, transform, world bounds; max 8000 nodes / depth 8), texts, dimensions, loose top-level entities, section planes. Lengths are mm (internal inch × 25.4). |
| `geom_probe.rb` | `geom_probe.json` (committed as `geometry_probe.json`) | For the definitions in `NAMES`: horizontal face levels and areas, sloped-face angle histogram, vertical face count, curves/arc radii. |
| `grouping_probe.rb` | `grouping_probe.json` | Every instance (depth ≤ 12) in dump order: pid path, tag, material, locked, hidden, glued_to, local identity/origin/axes, mirrored. Every definition: raw Face/Edge counts by tag, child instances by tag, bbox min/max, insertion point, behaviour (`cuts_opening`, `is2d`, `snapto`, …). Plus `model.modified?` and the active edit path. |
| `render_views.rb` | `view_*.png` | Writes 1600×1000 PNGs of the current view, each scene camera, an SW iso and a top view. It changes only the **camera** while rendering and restores the saved camera in `ensure`. PNGs are not committed. |

Output directory: `$SION_SU_EXPORT_DIR`, else `%USERPROFILE%\grokbot-mcp-bridge\export` (must exist).

## Running through the PC bridge (how the 0914 data was captured)

```powershell
[Console]::OutputEncoding=[Text.Encoding]::UTF8; cd "$env:USERPROFILE\grokbot-mcp-bridge"
# copy dump_model.rb into .\export\ first, then:
'{"code":"load ''<USER_HOME>/grokbot-mcp-bridge/export/dump_model.rb''"}' | Set-Content -Encoding utf8 args_dump.json
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs call claude:hueflow-sketchup execute_ruby --args-file args_dump.json --timeout 280000   # milliseconds
```

`load` returns `true`; check that the JSON file was written. Then rebuild the graph export:

```bash
uv run python -m sion_ingestion.sketchup_assets build          # writes data/bootstrap/sketchup-<ns>.json
uv run python -m sion_ingestion.sketchup_assets build --check  # CI-style freshness check
```

See `docs/SKETCHUP_KNOWLEDGE.md` for the graph layout and the ingest path.

## 객체별 온톨로지(블록 규칙·자산·레벨)

```bash
# SketchUp(읽기 전용): SION_SU_OUT 폴더에 hierarchy.json, objects.json, objects/<분류>/*.skp 생성
#   eval(File.read('scripts/sketchup/export_objects.rb'))
python -m sion_ingestion.sketchup_ontology \
  [--hierarchy data/sources/sketchup/0914-meeting/hierarchy.json] \
  [--objects data/sources/sketchup/0914-meeting/objects.json]      # -> data/bootstrap/sketchup-0914-meeting.ontology.json
python -m sion_ingestion.sketchup_ontology --check
```

- 나무·사람·차량·플랜터·가구·카운터·가져온 3D는 **블록 노드 하나**로만 기억(내부 형상 노드 생략, `collapsed_children`).
- 최상위·2단계 객체와 모든 블록 노드는 `stored_as_asset` → `Artifact`(상대경로 `objects/<분류>/<정의>__<pid>.skp`, sha256). 매니페스트가 없으면 `asset_state=planned`.
- 레벨(+5.0/+10.2/+14.6 m, ±400 mm)과 블록 판정은 `unverified` 후보 + `basis_ko`. 자동 승인 없음 → `/review`.
- `.skp` 바이너리와 개인 절대경로는 커밋하지 않는다.

## Exception: `regroup_0914.rb` (writes only when explicitly enabled)

`regroup_0914.rb` implements [`docs/sketchup/0914-REGROUP-PLAN.ko.md`](../../docs/sketchup/0914-REGROUP-PLAN.ko.md).
It defaults to `DRY_RUN = true` and only prints planned operations. With `DRY_RUN = false` it wraps all changes in one
`model.start_operation` (one Ctrl+Z). `PURGE`, `APPLY_NAMES` and `FIX_INNER_TAGS` are separate flags, off by default.
Agents must not run it with `DRY_RUN = false`; a human saves a copy of the model first.
