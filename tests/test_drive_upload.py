import hashlib

import pytest

from sion_drive_store import DriveUploadUnavailable, upload_with_service_account


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeFiles:
    def __init__(self):
        self.items = []  # dicts: id, name, parent, folder, md5

    def list(self, q, **_):
        def run():
            out = []
            for item in self.items:
                if f"name = '{item['name']}'" in q and f"'{item['parent']}' in parents" in q:
                    is_folder_q = "mimeType = '" in q
                    if item["folder"] == is_folder_q:
                        out.append({"id": item["id"], "name": item["name"], "md5Checksum": item["md5"]})
            return {"files": out}
        return _Req(run)

    def create(self, body, media_body=None, **_):
        def run():
            md5 = None
            if media_body is not None:
                with open(media_body if isinstance(media_body, str) else media_body._filename, "rb") as f:
                    md5 = hashlib.md5(f.read()).hexdigest()
            item = {"id": f"id{len(self.items)}", "name": body["name"], "parent": body["parents"][0],
                    "folder": "mimeType" in body, "md5": md5}
            self.items.append(item)
            return {"id": item["id"]}
        return _Req(run)


class FakeService:
    def __init__(self):
        self._files = FakeFiles()

    def files(self):
        return self._files


def test_upload_is_append_only_and_idempotent(tmp_path):
    stage = tmp_path / "stage"
    (stage / "objects").mkdir(parents=True)
    (stage / "objects" / "a.bin").write_bytes(b"abc")
    (stage / "m.json").write_text("{}", encoding="utf-8")
    svc = FakeService()
    first = upload_with_service_account(stage, root_folder_id="ROOT", service=svc)
    assert first["uploaded"] == 2 and first["conflicts"] == []
    second = upload_with_service_account(stage, root_folder_id="ROOT", service=svc)
    assert second["uploaded"] == 0 and second["skipped"] == 2
    (stage / "m.json").write_text('{"changed": 1}', encoding="utf-8")
    third = upload_with_service_account(stage, root_folder_id="ROOT", service=svc)
    assert third["conflicts"] == ["m.json"]
    assert sum(1 for i in svc.files().items if i["name"] == "m.json") == 1


def test_upload_requires_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("SION_DRIVE_ROOT_FOLDER_ID", raising=False)
    monkeypatch.delenv("SION_DRIVE_SERVICE_ACCOUNT", raising=False)
    with pytest.raises(DriveUploadUnavailable):
        upload_with_service_account(tmp_path)
    with pytest.raises(DriveUploadUnavailable):
        upload_with_service_account(tmp_path, root_folder_id="ROOT")
