from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from ontology_drive_store import LocalStageStore


def test_stage_store_is_content_addressed_and_idempotent(tmp_path: Path):
    source = tmp_path / "hello.txt"
    source.write_text("hello ontology", encoding="utf-8")

    store = LocalStageStore(tmp_path / "stage")
    first = store.put(source)
    second = store.put(source)

    assert first == second
    assert first.content_hash.startswith("sha256:")
    assert first.byte_size == len("hello ontology".encode())
    assert first.mime_type == "text/plain"
    assert first.provider == "local-stage"
    storage_uri = urlsplit(first.storage_uri)
    assert storage_uri.scheme == "file"
    assert Path(url2pathname(storage_uri.path)).exists()
