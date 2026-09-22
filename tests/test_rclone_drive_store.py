import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ontology_drive_store import RcloneDriveStore


def test_rclone_drive_store_uploads_immutably_and_reads_provider_id(tmp_path: Path):
    source = tmp_path / "drawing.dxf"
    source.write_bytes(b"ontology-drive-test")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    copy_result = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    stat_result = CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({
            "ID": "drive-file-id-123",
            "Size": source.stat().st_size,
            "MimeType": "application/dxf",
            "Hashes": {"SHA-256": digest},
        }),
        stderr="",
    )

    with patch("ontology_drive_store.store.subprocess.run", side_effect=[copy_result, stat_result]) as run:
        store = RcloneDriveStore("gdrive", ".CODE/_artifact-store")
        saved = store.put(source)

    copy_call = run.call_args_list[0].args[0]
    stat_call = run.call_args_list[1].args[0]
    assert copy_call[0:2] == ["rclone", "copyto"]
    assert "--immutable" in copy_call
    assert "--checksum" in copy_call
    assert stat_call[0:2] == ["rclone", "lsjson"]
    assert "--stat" in stat_call
    assert saved.provider == "google-drive-rclone"
    assert saved.provider_file_id == "drive-file-id-123"
    assert saved.content_hash == f"sha256:{digest}"
