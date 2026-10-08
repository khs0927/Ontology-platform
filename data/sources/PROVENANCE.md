# data/sources — provenance

## sion-map-production.json

| | |
|---|---|
| SHA-256 | `24f5c46825e8dc223577297cb457d43468bf3a0e6d8a11a6d8050f5fe31dd56f` (17,680 bytes, CRLF, kept byte-identical) |
| Schema | `ontology-map-export/v1`, namespace `sion-production`, declared source `sion://ontology-map/production/v1` |
| Content | 31 nodes (all 31 labels of `data/bootstrap/current-map-inventory.json`, category counts 6/4/5/6/4/6) and 43 relations with explicit `source_id`/`target_id` |
| Found in | Google Drive (owner private@example.invalid), two identical copies: `_ontology-platform-verify-20260924/data/bootstrap/` (file id `PRIVATE_DRIVE_ID`) and `_ontology-platform-openapi-20260924/data/bootstrap/` (file id `PRIVATE_DRIVE_ID`); same bytes on the Windows PC under `C:\code\_ontology-platform-verify-20260924\` and `C:\code\_ontology-platform-openapi-20260924\` |
| Git origin | `khs0927/Ontology-platform` PR #8 "feat(map): import production Sion ontology map with 31 nodes and 43 relations (P5)", merged 2026-09-24 02:55 KST (`c840863`, `a6bccd9` after the history rewrite). Removed 14 minutes later by `3e35521` (03:09 KST), which replaced the tree with the current code line; the 43 edges were never on the current `main` until now. |

### How much to trust it

PR #8 says the 31 labels were "preserved character-for-character" from the
inventory and that the 43 relations were "defined" to fit the platform's relation
types. In other words, the edges were authored when that PR was written. They
were **not** read out of the Sion Ontology Map Sites page (that page needs a
ChatGPT login and its edge endpoints were never exported). They match the
observed counts (31/43) and labels exactly, but individual edges may differ
from what the Sites page draws.

So `data/bootstrap/sion-map-export.json` (the converted file) imports all 43
edges as **unverified candidates** (`properties.candidate = true`), each with an
evidence row pointing to its `$.relations[i]` locator in this file. They show up
on `/review`. Approve or reject them there, or replace them with a structured
export of the Sites page when one exists:
`sion-relations import <export> --database-url ...`.

Three edges use `VALIDATES`. That type was added as the 15th core relation type
in `migrations/007_relation_type_validates.sql`.

### Searched without finding another edge source (2026-10-08 KST)

- Google Drive: all hits for the map labels or names are the two copies above, plus
  `current-map-inventory.json` copies (labels and counts only, no edges).
- Windows PC, `rg` over `C:\code` (except `C:\code\secrets`), the user profile, the
  `cokacremote_shared` mount and `D:\cokacmux-graph`. The map labels show up only in the two
  copies above, in `current-map-inventory.json` copies, and in agent session logs
  (`D:\cokacmux-graph\source-archive\aside\*\messages.jsonl` and their backup objects). The logs
  hold inventory and status text but no edge list (no `rel-43`, no `from`/`to` pairs).
- `git log --all -S` across the git repos in `C:\code`: map labels appear only in PR #8 (`c840863`),
  `3e35521`/`ed98e0c` (which remove it) and `3a48725` (label list only).
- No browser cache, cookies or credential stores were read.

## sketchup/0914-meeting/

| File | SHA-256 | Notes |
|---|---|---|
| `model_dump.json` | `33ebc367f6916e339fc9bc03a75a06403a7f37e4a6b8245e82b5c7e512a61bd6` (1,228,497 bytes, CRLF, byte-identical) | `scripts/sketchup/dump_model.rb` output, `_meta.dumped_at` 2026-10-08 10:39:38 KST |
| `geometry_probe.json` | `c7a26eaf9fe1424a56c46803eb75f964834d673c2f859abdce074d85ced042a8` (byte-identical) | `scripts/sketchup/geom_probe.rb` output (written as `geom_probe.json`), 95 definitions |
| `classification.json` | (authored) | Definition → class overlay. Every assignment is an inference from names, sizes, materials, levels and the probe; pinned to the dump sha256 above |
| `../object-classes.json` | (authored) | 30 object classes |

- Source model: `0914_담당미팅.skp` (`C:\Users\USER\Documents\카카오톡 받은 파일\`), open in
  SketchUp 25.0.634 on the user's Windows PC with **unsaved changes** (`modified=true`). The dump
  reflects the in-memory state at dump time, not the file on disk.
- Captured through the PC MCP bridge with `claude:hueflow-sketchup` `execute_ruby` (`load` of the
  scripts). The scripts are read-only: no geometry, tag, material, page or style was created,
  changed or deleted, nothing was saved, undone or purged. `render_views.rb` changed only the view
  camera to render PNGs and restored it.
- `.gitattributes` keeps `data/sources/**` byte-identical (`-text`).
- Not captured: the `.skp` file itself, texture images, plugin settings, anything inside definitions
  deeper than 8 levels (none were truncated: 619 hierarchy nodes, `truncated` 0).
