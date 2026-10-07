from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ArtifactDescriptor:
    schema: str
    stable_key: str
    sha256: str
    byte_size: int
    original_name: str
    mime_type: str
    object_relative_path: str
    manifest_relative_path: str
    storage_uri: str
    provider: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_artifact_record(self) -> dict:
        return {
            "stable_key": self.stable_key,
            "name": self.original_name,
            "storage_uri": self.storage_uri,
            "content_hash": self.sha256,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "provider": self.provider,
            "provider_file_id": None,
            "properties": {
                "object_relative_path": self.object_relative_path,
                "manifest_relative_path": self.manifest_relative_path,
                "artifact_schema": self.schema,
            },
        }


@dataclass(frozen=True)
class DriveLayout:
    """Canonical Google Drive layout for immutable Sion artifacts."""

    project_root: str = "AEC-INTELLIGENCE/01_PROJECTS/SION-ONTOLOGY"

    def object_destination(self, digest: str) -> str:
        return (
            f"{self.project_root}/00_SOURCES/objects/sha256/"
            f"{digest[:2]}/{digest}"
        )

    def manifest_destination(self, digest: str) -> str:
        return (
            f"{self.project_root}/00_SOURCES/manifests/"
            f"{digest}.json"
        )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


class LocalContentAddressedStore:
    """Immutable local staging area designed to mirror cleanly into Drive.

    Object paths are determined only by SHA-256. Existing objects are never
    overwritten unless their bytes match the requested digest.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        drive_layout: DriveLayout | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.drive_layout = drive_layout or DriveLayout()

    def put_file(self, source: str | Path) -> ArtifactDescriptor:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)

        digest = _sha256(source_path)
        size = source_path.stat().st_size
        relative_object = Path("objects") / "sha256" / digest[:2] / digest
        relative_manifest = Path("manifests") / f"{digest}.json"
        object_path = self.root / relative_object
        manifest_path = self.root / relative_manifest

        if object_path.exists():
            if object_path.stat().st_size != size or _sha256(object_path) != digest:
                raise RuntimeError(
                    f"content-address collision/corruption at {object_path}"
                )
        else:
            _atomic_copy(source_path, object_path)

        mime = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        descriptor = ArtifactDescriptor(
            schema="sion-artifact/v1",
            stable_key=f"artifact:sha256:{digest}",
            sha256=f"sha256:{digest}",
            byte_size=size,
            original_name=source_path.name,
            mime_type=mime,
            object_relative_path=relative_object.as_posix(),
            manifest_relative_path=relative_manifest.as_posix(),
            storage_uri=f"gdrive:///{self.drive_layout.object_destination(digest)}",
            provider="google_drive",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # The manifest may be refreshed for metadata such as the original
        # filename, while the content-addressed object remains immutable.
        _atomic_json(manifest_path, descriptor.to_dict())
        return descriptor

    def verify(self, descriptor: ArtifactDescriptor) -> bool:
        digest = descriptor.sha256.removeprefix("sha256:")
        object_path = self.root / descriptor.object_relative_path
        return (
            object_path.is_file()
            and object_path.stat().st_size == descriptor.byte_size
            and _sha256(object_path) == digest
        )
