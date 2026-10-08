# Cross-device sync architecture

## Principle

Do not use a Google Drive synchronized folder as the active Git working tree. Git, package managers, file watchers, SQLite/WAL files, and build outputs create rapid temporary changes and can cause conflict copies or partial states.

Sion uses three layers:

1. Local workspace - actual editing and builds.
2. Git/GitHub - canonical code history and multi-computer collaboration.
3. Google Drive - automatic safety copy, large artifacts, snapshots, recovery, and mobile access.

## Drive layout

.CODE/_sync-v2/
  devices/<device-id>/workspaces/C_CODE/...
  canonical/<project>/<git-sha>/...
  manifests/<device-id>/...
  history/<device-id>/...
  bootstrap/

AEC-INTELLIGENCE/01_PROJECTS/SION-ONTOLOGY/
  00_SOURCES/
  01_SNAPSHOTS/
  02_EXPORTS/
  09_RECOVERY/

## Automatic backup semantics

- Local additions/changes -> device-scoped Drive backup.
- Before a changed Drive file is replaced, its old version is copied into history.
- Local deletion -> recorded in the manifest only. It does not delete the Drive copy.
- .git, dependencies, virtual environments, build outputs, secrets, temp files, and DB WAL/SHM files are excluded.
- Each run writes a SHA-256 manifest and Git HEAD/status summary.

## Moving between computers

1. Clone or git pull the project on the destination computer.
2. Retrieve large project artifacts/data from Drive when needed.
3. If the previous computer had uncommitted work, inspect its device backup and recover only those files.
4. Each computer has a unique device-id, so device backups never overwrite another computer's workspace.

## Mobile

Mobile reads Drive artifacts/manifests and GitHub history. Mobile ChatGPT can instruct a connected remote worker to edit a local checkout. The phone does not need a writable Git working tree.

## Runtime databases

PostgreSQL/AGE/pgvector stay local. Drive receives logical dumps, migrations, canonical JSONL/JSON-LD/GraphML/Parquet exports, and checksummed snapshots. Live database files are never placed in a synced folder.

Platform assets use the Drive storage root directly (`SION_STORAGE_ROOT`). The API and import CLIs
export a DB snapshot and the whole graph there after each committed write (`sion_api.drive_export`),
so no scheduled copy job is needed. See `docs/STORAGE.md`.
