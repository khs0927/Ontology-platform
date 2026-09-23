from __future__ import annotations

import json
from pathlib import Path

from sion_drive_store import DriveLayout, LocalContentAddressedStore


def test_content_addressed_store_deduplicates_and_verifies(tmp_path: Path):
    source = tmp_path / "drawing.dxf"
    source.write_bytes(b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n")

    root = tmp_path / "lake"
    store = LocalContentAddressedStore(root)

    first = store.put_file(source)
    second = store.put_file(source)

    assert first.sha256 == second.sha256
    assert first.object_relative_path == second.object_relative_path
    assert store.verify(first)

    object_files = [p for p in (root / "objects").rglob("*") if p.is_file()]
    assert len(object_files) == 1

    manifest = json.loads(
        (root / first.manifest_relative_path).read_text(encoding="utf-8")
    )
    assert manifest["original_name"] == "drawing.dxf"
    assert manifest["storage_uri"].startswith("gdrive:///AEC-INTELLIGENCE/")


def test_drive_layout_is_hash_partitioned():
    layout = DriveLayout(project_root="Project")
    digest = "a" * 64
    assert layout.object_destination(digest) == (
        "Project/00_SOURCES/objects/sha256/aa/" + digest
    )
    assert layout.manifest_destination(digest) == (
        "Project/00_SOURCES/manifests/" + digest + ".json"
    )


def test_descriptor_maps_directly_to_artifact_metadata(tmp_path: Path):
    source = tmp_path / "model.ifc"
    source.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    store = LocalContentAddressedStore(tmp_path / "lake")
    descriptor = store.put_file(source)
    record = descriptor.to_artifact_record()

    digest = descriptor.sha256.removeprefix("sha256:")
    assert descriptor.stable_key == f"artifact:sha256:{digest}"
    assert descriptor.provider == "google_drive"
    assert record["stable_key"] == descriptor.stable_key
    assert record["content_hash"] == descriptor.sha256
    assert record["storage_uri"] == descriptor.storage_uri
    assert record["provider"] == "google_drive"
    assert record["properties"]["artifact_schema"] == "sion-artifact/v1"
