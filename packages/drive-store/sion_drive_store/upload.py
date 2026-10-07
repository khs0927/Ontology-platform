"""Publish staged artifacts into a mounted Google Drive folder.

This completes the local-desktop path. A service-account API upload is used
only when SION_DRIVE_SERVICE_ACCOUNT is set and google-api-python-client exists.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
import shutil

from sion_drive_store.store import DriveLayout
from sion_ingestion.agent_bridge import detect_google_drive_root


def publish_to_mounted_drive(stage_root: Path, drive_root: Path | None = None) -> dict:
    root = drive_root or detect_google_drive_root()
    if root is None:
        return {"published": False, "reason": "google drive root not mounted"}
    layout = DriveLayout()
    destination = root / layout.project_root
    copied = 0
    archived = 0
    for path in stage_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(stage_root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size == path.stat().st_size and target.read_bytes() == path.read_bytes():
                continue
            # AGENTS.md: changed destination files are copied to history before replacement.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            history = destination / ".history" / stamp / relative
            history.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, history)
            archived += 1
        shutil.copy2(path, target)
        copied += 1
    return {"published": True, "copied": copied, "archived": archived, "destination": str(destination)}


def service_account_configured() -> bool:
    return bool(os.environ.get("SION_DRIVE_SERVICE_ACCOUNT"))
