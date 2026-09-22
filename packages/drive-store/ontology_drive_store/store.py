from __future__ import annotations

import hashlib
import mimetypes
import shutil
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
    """Content-addressed staging area used before cloud upload.

    This is deliberately non-destructive and contains no Google credentials.
    A Google Drive adapter can consume the staged object and return a Drive file id.
    """

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
