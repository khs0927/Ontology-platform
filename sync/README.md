# Ontology Drive Sync v2

The backup model is device-scoped and non-destructive.

## Rules

- Do not develop inside a Google Drive synchronized folder.
- GitHub is the source of truth for code.
- Drive stores safety copies, snapshots, exports, recovery data, and large artifacts.
- Do not use destructive mirror behavior such as robocopy /MIR or rclone sync for working backups.
- A missing local file is recorded as a tombstone; it does not automatically delete the Drive copy.
- Secrets, dependency trees, caches, build output, and live DB WAL/SHM files are excluded.

## Drive path

Do not assume a fixed drive letter such as G:. Google Drive for Desktop can use a different drive letter or localized folder name. Platform-specific installers must detect the mounted Drive path or use an authenticated API/rclone remote.

## Manual engine

`ontology_sync.py` implements the non-destructive copy semantics. Windows scheduling/Drive path discovery will be shipped only after it is verified on the target machine.
