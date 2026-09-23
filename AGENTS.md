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
- khs0927/Ontology is an optional AEC/CAIR integration source, not a hard dependency of the core platform.
- Check licenses and tests before adopting external code.
