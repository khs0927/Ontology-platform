"""Publish staged artifacts into a mounted Google Drive folder.

This completes the local-desktop path. A service-account API upload is used
only when SION_DRIVE_SERVICE_ACCOUNT is set and google-api-python-client exists.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sion_ingestion.agent_bridge import detect_google_drive_root

from sion_drive_store.store import DriveLayout

HISTORY_DIR = ".history"


def _same_content(a: Path, b: Path, chunk: int = 1 << 20) -> bool:
    """Byte comparison without ``filecmp``'s stat-keyed cache (unsafe with coarse mtimes)."""
    if a.stat().st_size != b.stat().st_size:
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            left, right = fa.read(chunk), fb.read(chunk)
            if left != right:
                return False
            if not left:
                return True


def publish_to_mounted_drive(stage_root: Path, drive_root: Path | None = None) -> dict:
    """Copy staged files into the mounted Drive project folder, one way, never deleting.

    AGENTS.md: a destination file whose *content* differs is first copied to
    ``<destination>/.history/<UTC timestamp>/<relative path>``, then replaced. Identical
    files are skipped (compared byte for byte, not by size). Files that exist only on
    Drive are left alone.
    """
    root = drive_root or detect_google_drive_root()
    if root is None:
        return {"published": False, "reason": "google drive root not mounted"}
    layout = DriveLayout()
    destination = root / layout.project_root
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    history_root = destination / HISTORY_DIR / stamp
    copied = 0
    unchanged = 0
    archived: list[str] = []
    for path in sorted(stage_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(stage_root)
        if relative.parts and relative.parts[0] == HISTORY_DIR:
            continue  # never publish a history tree over the Drive history
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            if _same_content(path, target):
                unchanged += 1
                continue
            backup = history_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            archived.append(relative.as_posix())
        shutil.copy2(path, target)
        copied += 1
    return {
        "published": True,
        "copied": copied,
        "unchanged": unchanged,
        "archived": len(archived),
        "archived_paths": archived,
        "history": str(history_root) if archived else None,
        "destination": str(destination),
    }


def service_account_configured() -> bool:
    return bool(os.environ.get("SION_DRIVE_SERVICE_ACCOUNT"))


class DriveUploadUnavailable(RuntimeError):
    """Raised when the optional service-account upload path is not usable."""


_FOLDER_MIME = "application/vnd.google-apps.folder"
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def build_service_account_client(credentials_path: str | None = None):
    """Build a Drive v3 client from a service-account JSON *path*.

    The path is read from ``SION_DRIVE_SERVICE_ACCOUNT`` when not given. The
    key content is never logged or returned. Requires the optional ``drive``
    extra (google-api-python-client + google-auth).
    """
    path = credentials_path or os.environ.get("SION_DRIVE_SERVICE_ACCOUNT")
    if not path:
        raise DriveUploadUnavailable("SION_DRIVE_SERVICE_ACCOUNT is not set")
    if not Path(path).is_file():
        raise DriveUploadUnavailable("service-account credential file not found")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DriveUploadUnavailable(
            "install the optional extra: pip install 'sion-ontology-platform[drive]'"
        ) from exc
    creds = service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def _find_child(service, parent_id: str, name: str, folder: bool) -> dict | None:
    mime = f" and mimeType = '{_FOLDER_MIME}'" if folder else f" and mimeType != '{_FOLDER_MIME}'"
    query = f"'{parent_id}' in parents and name = '{_escape(name)}' and trashed = false{mime}"
    found = service.files().list(
        q=query, fields="files(id,name,size)", supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = found.get("files", [])
    return files[0] if files else None


def _ensure_folder(service, parent_id: str, name: str) -> str:
    existing = _find_child(service, parent_id, name, folder=True)
    if existing:
        return existing["id"]
    created = service.files().create(
        body={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]},
        fields="id", supportsAllDrives=True,
    ).execute()
    return created["id"]


def upload_with_service_account(
    stage_root: Path,
    folder_id: str | None = None,
    *,
    service=None,
    credentials_path: str | None = None,
    media_factory=None,
) -> dict:
    """Upload staged artifacts into a Drive folder, non-destructively.

    * Never deletes or overwrites remote files. A same-name file with the same
      size is skipped; a same-name file with a different size is reported as a
      conflict and left untouched (content-addressed objects should not differ).
    * ``folder_id`` defaults to ``SION_DRIVE_FOLDER_ID``. The target folder
      must be shared with the service account.
    """
    folder_id = folder_id or os.environ.get("SION_DRIVE_FOLDER_ID")
    if not folder_id:
        raise DriveUploadUnavailable("SION_DRIVE_FOLDER_ID is not set")
    if service is None:
        service = build_service_account_client(credentials_path)
    if media_factory is None:
        from googleapiclient.http import MediaFileUpload

        def media_factory(path: Path):
            return MediaFileUpload(str(path), resumable=path.stat().st_size > 5 * 1024 * 1024)

    folder_cache: dict[tuple[str, ...], str] = {(): folder_id}
    uploaded, skipped, conflicts = 0, 0, []
    for path in sorted(p for p in Path(stage_root).rglob("*") if p.is_file()):
        parts = path.relative_to(stage_root).parts
        parent = folder_id
        for depth in range(1, len(parts)):
            key = parts[:depth]
            if key not in folder_cache:
                folder_cache[key] = _ensure_folder(service, parent, parts[depth - 1])
            parent = folder_cache[key]
        existing = _find_child(service, parent, parts[-1], folder=False)
        if existing is not None:
            if str(existing.get("size")) == str(path.stat().st_size):
                skipped += 1
            else:
                conflicts.append("/".join(parts))
            continue
        service.files().create(
            body={"name": parts[-1], "parents": [parent]},
            media_body=media_factory(path), fields="id", supportsAllDrives=True,
        ).execute()
        uploaded += 1
    return {"published": True, "uploaded": uploaded, "skipped": skipped, "conflicts": conflicts}
