"""Coverage for write auth, ingestion routes, IFC fallback and Drive uploader."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sion_api.auth import AuthPolicy
from sion_api.main import create_app
from sion_drive_store import DriveUploadUnavailable, upload_with_service_account
from sion_ingestion.dxf_ingest import parse_dxf
from sion_ingestion.ifc_ingest import build_ifc_export, parse_ifc

WRITE = "write-token-12345678901"
READ = "read-token-123456789012"

IFC_SAMPLE = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,'Demo Project',$,$,$,$,$,$);
#10=IFCBUILDINGSTOREY('2dQFggKBb1fOc1CqZDIDlx',$,'Level 1',$,$,$,$,$,.ELEMENT.,0.);
#20=IFCWALL('3vB2YO$MX4xv5uCqZZG05x',$,'Wall ''A''',$,$,$,$,$,$);
#21=IFCDOOR('1hOSvn6df7F8_7GcBWlRGQ',$,'Door 01',$,$,$,$,$,$,$,$);
#30=IFCCARTESIANPOINT((0.,0.,0.));
ENDSEC;
END-ISO-10303-21;
"""

POST_ROUTES = [
    "/api/v1/entities",
    "/api/v1/relations",
    "/api/v1/evidence",
    "/api/v1/artifacts",
    "/api/v1/ingest/documents",
    "/api/v1/ingest/dxf",
    "/api/v1/ingest/ifc",
    "/api/v1/graphrag/project",
]


def bearer_app(tmp_path: Path | None = None):
    policy = AuthPolicy(
        mode="bearer",
        token_scopes=(
            (WRITE, frozenset({"read:knowledge", "write:knowledge"})),
            (READ, frozenset({"read:knowledge"})),
        ),
    )
    return create_app(
        database_url="sqlite://",
        auto_create_schema=True,
        auth_policy=policy,
        ingest_roots=[tmp_path] if tmp_path else [],
    )


@pytest.mark.parametrize("route", POST_ROUTES)
def test_post_routes_require_bearer(route):
    with TestClient(bearer_app()) as c:
        assert c.post(route, json={}).status_code == 401
        bad = c.post(route, json={}, headers={"Authorization": "Bearer wrong-token-000000000"})
        assert bad.status_code == 401
        ro = c.post(route, json={}, headers={"Authorization": f"Bearer {READ}"})
        assert ro.status_code == 403


def test_local_only_rejects_remote_clients():
    app = create_app(database_url="sqlite://", auto_create_schema=True,
                     auth_policy=AuthPolicy(mode="local-only"))
    with TestClient(app, client=("203.0.113.7", 50000)) as c:
        r = c.post("/api/v1/entities", json={"stable_key": "x", "entity_type_id": "Concept",
                                             "name": "x", "properties": {}})
        assert r.status_code == 403
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200


def test_local_or_bearer_requires_token_remotely():
    policy = AuthPolicy(mode="local-or-bearer", token_scopes=((WRITE, frozenset({"*"})),))
    app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy)
    body = {"stable_key": "concept:r", "entity_type_id": "Concept", "name": "R", "properties": {}}
    with TestClient(app, client=("203.0.113.7", 50000)) as c:
        assert c.post("/api/v1/entities", json=body).status_code == 401
        ok = c.post("/api/v1/entities", json=body, headers={"Authorization": f"Bearer {WRITE}"})
        assert ok.status_code == 201


def test_auth_policy_from_env_validation(monkeypatch):
    monkeypatch.setenv("SION_API_AUTH_MODE", "bearer")
    monkeypatch.delenv("SION_API_TOKENS_JSON", raising=False)
    with pytest.raises(RuntimeError):
        AuthPolicy.from_env()
    monkeypatch.setenv("SION_API_TOKENS_JSON", '{"short": ["*"]}')
    with pytest.raises(RuntimeError):
        AuthPolicy.from_env()
    monkeypatch.setenv("SION_API_TOKENS_JSON", f'{{"{WRITE}": ["write:knowledge"]}}')
    policy = AuthPolicy.from_env()
    assert policy.mode == "bearer"
    monkeypatch.setenv("SION_API_AUTH_MODE", "open")
    with pytest.raises(RuntimeError):
        AuthPolicy.from_env()


def test_ingest_routes_round_trip_with_evidence(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text("# Pump room\n## Valve\n", encoding="utf-8")
    dxf = tmp_path / "plan.dxf"
    dxf.write_text("0\nSECTION\n2\nENTITIES\n0\nTEXT\n8\nA-NOTE\n1\nDOOR\n0\nLINE\n8\nA-WALL\n"
                   "0\nLWPOLYLINE\n8\nA-ROOM\n70\n1\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    ifc = tmp_path / "model.ifc"
    ifc.write_text(IFC_SAMPLE, encoding="utf-8")
    headers = {"Authorization": f"Bearer {WRITE}"}
    with TestClient(bearer_app(tmp_path)) as c:
        r = c.post("/api/v1/ingest/documents", json={"paths": [str(doc)]}, headers=headers)
        assert r.status_code == 200 and r.json()["evidence_created"] == 2
        r = c.post("/api/v1/ingest/dxf", json={"path": str(dxf)}, headers=headers)
        assert r.status_code == 200 and r.json()["created_edges"] == 3
        r = c.post("/api/v1/ingest/ifc", json={"path": str(ifc)}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["created_edges"] == 4
        # idempotent
        again = c.post("/api/v1/ingest/ifc", json={"path": str(ifc)}, headers=headers).json()
        assert again["created_edges"] == 0 and again["evidence_created"] == 0
        evidence = c.get("/api/v1/evidence", headers=headers).json()
        assert evidence and all(e["verification_state"] == "unverified" for e in evidence)
        graph = c.get("/api/v1/graph", headers=headers).json()
        assert len(graph["edges"]) == 9
        # path confinement
        outside = c.post("/api/v1/ingest/dxf", json={"path": "/etc/passwd.dxf"}, headers=headers)
        assert outside.status_code == 403


def test_ingest_without_roots_refused_in_bearer_mode(tmp_path):
    with TestClient(bearer_app()) as c:
        r = c.post("/api/v1/ingest/documents", json={"paths": [str(tmp_path / "a.md")]},
                   headers={"Authorization": f"Bearer {WRITE}"})
        assert r.status_code == 403


def test_dxf_line_and_closed_polyline(tmp_path):
    dxf = tmp_path / "p.dxf"
    dxf.write_text("0\nSECTION\n2\nENTITIES\n0\nLINE\n8\nW\n0\nLWPOLYLINE\n8\nR\n70\n1\n"
                   "0\nLWPOLYLINE\n8\nP\n70\n0\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    kinds = [item["kind"] for item in parse_dxf(dxf)]
    assert kinds == ["segment", "space", "segment"]


def test_ifc_fallback_parser(tmp_path):
    ifc = tmp_path / "m.ifc"
    ifc.write_text(IFC_SAMPLE, encoding="utf-8")
    items, parser = parse_ifc(ifc, prefer_ifcopenshell=False)
    assert parser == "step-fallback"
    names = {i["name"] for i in items}
    assert names == {"Demo Project", "Level 1", "Wall 'A'", "Door 01"}
    export, _ = build_ifc_export(ifc, prefer_ifcopenshell=False)
    types = {n.entity_type_id for n in export.nodes}
    assert types == {"Artifact", "Concept", "SystemComponent"}


def test_map_page_served():
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True)) as c:
        r = c.get("/map")
        assert r.status_code == 200
        assert "/api/v1/graph" in r.text


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeDrive:
    def __init__(self):
        self.items: list[dict] = []

    def files(self):
        return self

    def list(self, q, **_):
        parent = q.split("'")[1]
        name = q.split("name = '")[1].split("' and")[0]
        folder = "mimeType = " in q
        hits = [i for i in self.items if i["parent"] == parent and i["name"] == name
                and i["folder"] == folder]
        return _Exec({"files": hits})

    def create(self, body, media_body=None, **_):
        item = {"id": f"id{len(self.items)}", "name": body["name"], "parent": body["parents"][0],
                "folder": body.get("mimeType", "").endswith("folder"),
                "size": media_body if media_body is not None else None}
        self.items.append(item)
        return _Exec({"id": item["id"]})


def test_service_account_uploader_non_destructive(tmp_path):
    (tmp_path / "objects" / "ab").mkdir(parents=True)
    (tmp_path / "objects" / "ab" / "abc").write_bytes(b"hello")
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "abc.json").write_text("{}")
    drive = FakeDrive()
    size = lambda p: p.stat().st_size  # fake media carries size
    first = upload_with_service_account(tmp_path, "root", service=drive, media_factory=size)
    assert first["uploaded"] == 2
    second = upload_with_service_account(tmp_path, "root", service=drive, media_factory=size)
    assert second == {"published": True, "uploaded": 0, "skipped": 2, "conflicts": []}
    (tmp_path / "manifests" / "abc.json").write_text('{"changed": true}')
    third = upload_with_service_account(tmp_path, "root", service=drive, media_factory=size)
    assert third["conflicts"] == ["manifests/abc.json"] and third["uploaded"] == 0


def test_service_account_uploader_unavailable_without_config(tmp_path, monkeypatch):
    monkeypatch.delenv("SION_DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("SION_DRIVE_SERVICE_ACCOUNT", raising=False)
    with pytest.raises(DriveUploadUnavailable):
        upload_with_service_account(tmp_path)
    with pytest.raises(DriveUploadUnavailable):
        upload_with_service_account(tmp_path, "folder")
