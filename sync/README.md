# Sion Drive Sync v2

This replaces the old /MIR model with device-scoped, non-destructive backups.

Windows:
  powershell -ExecutionPolicy Bypass -File .\sync\install-windows.ps1 -DeviceId home-bedroom

Use a different DeviceId on every other computer, for example office.

The scheduled task backs up C:\CODE every 5 minutes by default.

Manual backup:
  python .\sync\sion_sync.py backup --source C:\CODE --drive-root "G:\내 드라이브\.CODE\_sync-v2" --device-id home-bedroom --workspace-name C_CODE --state-dir C:\SionSync\state

Canonical promotion (clean Git tree only):
  python .\sync\sion_sync.py promote --project C:\CODE\sion-ontology-platform --drive-root "G:\내 드라이브\.CODE\_sync-v2"

Safety:
- Device backups never auto-delete Drive files.
- Local deletions are recorded in manifests.
- Previous destination content is saved under history before replacement.
- Secrets, dependency trees, caches, and build output are excluded.
