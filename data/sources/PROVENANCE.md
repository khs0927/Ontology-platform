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
