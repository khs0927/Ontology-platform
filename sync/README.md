# Sion Drive Sync v2

Device-scoped, one-way, non-destructive local sync and recovery staging. This is not a claim of automatic production backup or a live database mirror.

Windows:
  powershell -ExecutionPolicy Bypass -File .\sync\install-windows.ps1 -DeviceId device-example

Use a different DeviceId on every other computer, for example office.

The installer prepares a recurring local Windows task. Whether it can be registered autonomously depends on the host and credentials; it is not a production cloud scheduler guarantee.

Manual sync:
  python .\sync\sion_sync.py backup --source C:\CODE --drive-root "G:\내 드라이브\.CODE\_sync-v2" --device-id device-example --workspace-name C_CODE --state-dir C:\SionSync\state

Canonical promotion (clean Git tree only):
  python .\sync\sion_sync.py promote --project C:\CODE\sion-ontology-platform --drive-root "G:\내 드라이브\.CODE\_sync-v2"

Safety and current limits:
- Device backups never auto-delete Drive files.
- Local deletions are recorded in manifests.
- Previous destination content is saved under history before replacement.
- Secrets, dependency trees, caches, and build output are excluded.
- Local file replacement is atomic and manifests report verification status.
- Content-addressed Drive staging is partial; an authenticated production uploader/scheduler and production release evidence remain incomplete.
- Do not place a live PostgreSQL database in the Drive-synced tree.

For the implementation/partial/planned matrix and release blockers, see [../docs/STATUS.md](../docs/STATUS.md). Verification commands and the manually maintained **52+ targeted tests** baseline are maintained only in [../docs/STATUS.md#verification-baseline](../docs/STATUS.md#verification-baseline).
