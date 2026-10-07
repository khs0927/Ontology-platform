from sion_drive_store.store import DriveLayout
from sion_drive_store.upload import publish_to_mounted_drive, service_account_configured
from sion_ingestion.dxf_ingest import parse_dxf


def _stage(tmp_path, content: str):
    stage = tmp_path / "stage"
    (stage / "a").mkdir(parents=True, exist_ok=True)
    (stage / "a" / "f.txt").write_text(content, encoding="utf-8")
    return stage


def test_publish_copies_then_skips_identical(tmp_path):
    drive = tmp_path / "drive"
    stage = _stage(tmp_path, "one")
    assert publish_to_mounted_drive(stage, drive)["copied"] == 1
    again = publish_to_mounted_drive(stage, drive)
    assert again["copied"] == 0 and again["archived"] == 0


def test_publish_archives_changed_same_size_file(tmp_path):
    drive = tmp_path / "drive"
    publish_to_mounted_drive(_stage(tmp_path, "one"), drive)
    result = publish_to_mounted_drive(_stage(tmp_path, "two"), drive)
    assert result["copied"] == 1 and result["archived"] == 1
    root = drive / DriveLayout().project_root
    assert (root / "a" / "f.txt").read_text(encoding="utf-8") == "two"
    history = list((root / ".history").rglob("f.txt"))
    assert history and history[0].read_text(encoding="utf-8") == "one"


def test_publish_never_deletes_destination_extras(tmp_path):
    drive = tmp_path / "drive"
    root = drive / DriveLayout().project_root
    root.mkdir(parents=True, exist_ok=True)
    (root / "keep.txt").write_text("x", encoding="utf-8")
    publish_to_mounted_drive(_stage(tmp_path, "one"), drive)
    assert (root / "keep.txt").exists()


def test_service_account_flag(monkeypatch):
    monkeypatch.delenv("SION_DRIVE_SERVICE_ACCOUNT", raising=False)
    assert service_account_configured() is False
    monkeypatch.setenv("SION_DRIVE_SERVICE_ACCOUNT", "/nonexistent.json")
    assert service_account_configured() is True


def test_dxf_parser_line_and_polylines(tmp_path):
    path = tmp_path / "p.dxf"
    path.write_text(
        "0\nSECTION\n2\nENTITIES\n0\nLINE\n8\nA-WALL\n0\nLWPOLYLINE\n8\nA-ROOM\n70\n1\n"
        "0\nLWPOLYLINE\n8\nA-PIPE\n70\n0\n0\nENDSEC\n0\nEOF\n",
        encoding="utf-8",
    )
    kinds = [(i["kind"], i["name"]) for i in parse_dxf(path)]
    assert ("segment", "line:A-WALL") in kinds
    assert ("space", "space:A-ROOM") in kinds
    assert ("segment", "polyline:A-PIPE") in kinds
