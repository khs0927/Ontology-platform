# SketchUp read-only extraction scripts

Ruby scripts that produced `data/sources/sketchup/0914-meeting/*`. They run inside SketchUp
through an MCP server's Ruby tool (`claude:hueflow-sketchup` `execute_ruby`, or
`sketchup-mcp2` `eval_ruby`). **They never modify the model**: no geometry, tag, material,
page or style is created, moved or deleted, and nothing calls `model.save`, `undo` or purge.

| Script | Output | Notes |
|---|---|---|
| `dump_model.rb` | `model_dump.json` | Model info, units, shadow/geo info, styles, scenes + cameras, tags (usage per entity type), materials (texture, usage), all definitions (entity counts, face area, child definitions, tags/materials used, behaviour, attributes), the instance hierarchy (persistent id, path, tag, material, transform, world bounds; max 8000 nodes / depth 8), texts, dimensions, loose top-level entities, section planes. Lengths are mm (internal inch × 25.4). |
| `geom_probe.rb` | `geom_probe.json` (committed as `geometry_probe.json`) | For the definitions in `NAMES`: horizontal face levels and areas, sloped-face angle histogram, vertical face count, curves/arc radii. |
| `render_views.rb` | `view_*.png` | Writes 1600×1000 PNGs of the current view, each scene camera, an SW iso and a top view. It changes only the **camera** while rendering and restores the saved camera in `ensure`. PNGs are not committed. |

Output directory: `$SION_SU_EXPORT_DIR`, else `%USERPROFILE%\grokbot-mcp-bridge\export` (must exist).

## Running through the PC bridge (how the 0914 data was captured)

```powershell
[Console]::OutputEncoding=[Text.Encoding]::UTF8; cd "$env:USERPROFILE\grokbot-mcp-bridge"
# copy dump_model.rb into .\export\ first, then:
'{"code":"load ''C:/Users/<user>/grokbot-mcp-bridge/export/dump_model.rb''"}' | Set-Content -Encoding utf8 args_dump.json
& "C:\Program Files\nodejs\node.exe" mcp-call.mjs call claude:hueflow-sketchup execute_ruby --args-file args_dump.json --timeout 300
```

`load` returns `true`; check that the JSON file was written. Then rebuild the graph export:

```bash
uv run python -m sion_ingestion.sketchup_assets build          # writes data/bootstrap/sketchup-<ns>.json
uv run python -m sion_ingestion.sketchup_assets build --check  # CI-style freshness check
```

See `docs/SKETCHUP_KNOWLEDGE.md` for the graph layout and the ingest path.
