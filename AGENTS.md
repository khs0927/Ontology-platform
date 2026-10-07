# Sion Ontology Platform - Agent Instructions

## Workspace
- This repository is a local working copy. Edit here, not inside a Google Drive synchronized folder.
- Preserve existing files and uncommitted changes.
- Do not expose secrets, OAuth tokens, Doppler values, .env files, or private keys.

## Source of truth
- Git/GitHub is the canonical source for code history.
- Google Drive is the automatic backup, artifact lake, recovery store, and cross-device handoff layer.
- Runtime databases are local/rebuildable. Back up dumps/snapshots, never live PostgreSQL/SQLite WAL files.

## Drive sync safety
- Never use destructive mirror semantics such as robocopy /MIR or rclone sync for working backups.
- Automatic backups are one-way local -> Drive and device-scoped.
- Never automatically delete a Drive backup because a local file disappeared.
- Changed destination files must be copied to history before replacement.
- Exclude .git, dependencies, build/cache folders, secrets, live database lock files, and editor temp files.
- A canonical Drive snapshot may be promoted only from a clean Git working tree.

## Integration
- This is the main monorepo. ArchOntos (`packages/regulation`), Ontology (`packages/aec`) and GOD-CAD
  (`packages/cad/god-cad`) are git subtrees: edit them here, keep their own tests and CI green
  (`.github/workflows/regulation.yml`, `aec.yml`), and do not rebase branches that contain subtree merges.
- power-cad-mcp, hs-steel-cad, korean-land-mcp, HS-CAD, All-In-Cad and CAD-MCP are separate repos bridged by
  the contracts in `docs/INTEGRATION_CONTRACTS.md` / `sion_core.contracts`. Do not change those repos from
  here. When an upstream contract changes, update the schema, the pinned commit and the contract tests in
  one PR.
- Sion never executes CAD mutations. Data from bridged repos is evidence or request-scoped facts, never
  canonical state.
- All DXF reading goes through `sion_cad.reader` (ezdxf + built-in fallback).
- Check licenses and tests before adopting external code.
