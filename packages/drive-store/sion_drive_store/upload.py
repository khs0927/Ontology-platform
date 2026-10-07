"""Publish staged artifacts into a mounted Google Drive folder.

This completes the local-desktop path. A service-account API upload is used
only when SION_DRIVE_SERVICE_ACCOUNT is set and google-api-python-client exists.
"""

from __future__ import annotations

import os
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
    for path in stage_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(stage_root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size == path.stat().st_size:
            continue
        shutil.copy2(path, target)
        copied += 1
    return {"published": True, "copied": copied, "destination": str(destination)}


def service_account_configured() -> bool:
    return bool(
        os.environ.get("SION_DRIVE_OAUTH_TOKEN") or os.environ.get("SION_DRIVE_SERVICE_ACCOUNT")
    )


class DriveUploadUnavailable(RuntimeError):
    """Raised when the Drive API path is not configured or not installed."""


_FOLDER_MIME = "application/vnd.google-apps.folder"


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


USER_SCOPES = ["https://www.googleapis.com/auth/drive"]


def build_drive_service(credentials_path: str | None = None):
    """Build a Drive v3 client.

    Preference order:
    1. ``SION_DRIVE_OAUTH_TOKEN``: an authorized-user token JSON created by
       ``scripts/drive_oauth_login.py``. Works on personal Gmail accounts,
       where service accounts have no storage quota.
    2. ``SION_DRIVE_SERVICE_ACCOUNT``: a service-account key (needs a shared
       drive or Workspace delegation to actually store files).

    Credential contents are never logged or returned.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise DriveUploadUnavailable("install the 'drive' extra") from exc

    token_path = os.environ.get("SION_DRIVE_OAUTH_TOKEN")
    if token_path and not credentials_path:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(token_path, USER_SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            Path(token_path).write_text(creds.to_json(), encoding="utf-8")
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    path = credentials_path or os.environ.get("SION_DRIVE_SERVICE_ACCOUNT")
    if not path:
        raise DriveUploadUnavailable(
            "set SION_DRIVE_OAUTH_TOKEN or SION_DRIVE_SERVICE_ACCOUNT"
        )
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        path, scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_child(service, parent_id: str, name: str, *, folder: bool) -> dict | None:
    mime = f" and mimeType = '{_FOLDER_MIME}'" if folder else f" and mimeType != '{_FOLDER_MIME}'"
    response = service.files().list(
        q=f"name = '{_q(name)}' and '{_q(parent_id)}' in parents and trashed = false{mime}",
        fields="files(id, name, md5Checksum, size)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = response.get("files", [])
    return files[0] if files else None


def _ensure_folder(service, parent_id: str, parts: list[str], cache: dict) -> str:
    current = parent_id
    for part in parts:
        key = (current, part)
        if key not in cache:
            found = _find_child(service, current, part, folder=True)
            if found is None:
                found = service.files().create(
                    body={"name": part, "mimeType": _FOLDER_MIME, "parents": [current]},
                    fields="id",
                    supportsAllDrives=True,
                ).execute()
            cache[key] = found["id"]
        current = cache[key]
    return current


def upload_with_service_account(
    stage_root: Path,
    *,
    root_folder_id: str | None = None,
    service=None,
) -> dict:
    """Upload staged artifacts to Drive via the API, append-only.

    * existing file with identical MD5 -> skipped
    * existing file with different content -> left untouched, reported as conflict
      (never overwritten or deleted, per AGENTS.md backup rules)
    """
    import hashlib

    folder_id = root_folder_id or os.environ.get("SION_DRIVE_ROOT_FOLDER_ID")
    if not folder_id:
        raise DriveUploadUnavailable("SION_DRIVE_ROOT_FOLDER_ID is not set")
    if service is None:
        service = build_drive_service()
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:  # pragma: no cover - tests inject a fake service
        MediaFileUpload = None  # type: ignore[assignment]

    layout = DriveLayout()
    cache: dict = {}
    uploaded, skipped, conflicts = 0, 0, []
    for path in sorted(stage_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(stage_root).parts
        parent = _ensure_folder(
            service, folder_id, layout.project_root.split("/") + list(relative[:-1]), cache
        )
        md5 = hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - Drive's checksum
        existing = _find_child(service, parent, relative[-1], folder=False)
        if existing is not None:
            if existing.get("md5Checksum") == md5:
                skipped += 1
            else:
                conflicts.append("/".join(relative))
            continue
        media = MediaFileUpload(str(path), resumable=True) if MediaFileUpload else str(path)
        service.files().create(
            body={"name": relative[-1], "parents": [parent]},
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        uploaded += 1
    return {"published": True, "uploaded": uploaded, "skipped": skipped, "conflicts": conflicts}


def publish(stage_root: Path, drive_root: Path | None = None) -> dict:
    """Prefer the Drive API when configured, else the mounted folder."""
    if service_account_configured() and os.environ.get("SION_DRIVE_ROOT_FOLDER_ID"):
        return {"mode": "api", **upload_with_service_account(stage_root)}
    return {"mode": "mounted", **publish_to_mounted_drive(stage_root, drive_root)}
