from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


def sha256_file(path: str | Path) -> str:
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class StoredArtifact:
    storage_uri: str
    content_hash: str
    byte_size: int
    mime_type: str | None
    provider: str
    provider_file_id: str | None = None


class ArtifactStore(Protocol):
    def put(self, source: str | Path) -> StoredArtifact:
        ...


class LocalStageStore:
    """Content-addressed staging area used before cloud upload."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, source: str | Path) -> StoredArtifact:
        source_path = Path(source)
        digest = sha256_file(source_path)
        target = self.root / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source_path, target)

        mime_type, _ = mimetypes.guess_type(source_path.name)
        return StoredArtifact(
            storage_uri=target.resolve().as_uri(),
            content_hash=f"sha256:{digest}",
            byte_size=source_path.stat().st_size,
            mime_type=mime_type,
            provider="local-stage",
        )


class RcloneDriveStore:
    """Google Drive artifact provider backed by an external rclone remote.

    rclone owns OAuth/configuration. The application receives only the remote
    name and base path; secrets are not stored in this repository.
    """

    def __init__(self, remote: str, base_path: str, *, rclone_bin: str = "rclone"):
        self.remote = remote.rstrip(":")
        self.base_path = base_path.strip("/")
        self.rclone_bin = rclone_bin

    def _target(self, digest: str) -> str:
        suffix = f"{digest[:2]}/{digest}"
        path = f"{self.base_path}/{suffix}" if self.base_path else suffix
        return f"{self.remote}:{path}"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.rclone_bin, *args],
            check=True,
            text=True,
            capture_output=True,
        )

    def put(self, source: str | Path) -> StoredArtifact:
        source_path = Path(source)
        digest = sha256_file(source_path)
        target = self._target(digest)

        self._run(
            "copyto",
            str(source_path),
            target,
            "--immutable",
            "--checksum",
        )
        result = self._run(
            "lsjson",
            target,
            "--stat",
            "--hash",
            "--hash-type",
            "SHA-256",
        )
        info = json.loads(result.stdout)

        remote_size = info.get("Size")
        if remote_size is not None and int(remote_size) != source_path.stat().st_size:
            raise RuntimeError("rclone Drive object size does not match local source")

        remote_hash = (info.get("Hashes") or {}).get("SHA-256")
        if remote_hash and remote_hash.lower() != digest:
            raise RuntimeError("rclone Drive object SHA-256 does not match local source")

        provider_file_id = info.get("ID")
        if not provider_file_id:
            raise RuntimeError("rclone Drive object did not expose a provider ID")

        mime_type = info.get("MimeType") or mimetypes.guess_type(source_path.name)[0]
        return StoredArtifact(
            storage_uri=f"rclone://{self.remote}/{self.base_path}/{digest[:2]}/{digest}",
            content_hash=f"sha256:{digest}",
            byte_size=source_path.stat().st_size,
            mime_type=mime_type,
            provider="google-drive-rclone",
            provider_file_id=str(provider_file_id),
        )
