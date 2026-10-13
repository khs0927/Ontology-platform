from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sion_ingestion.asset_index import AssetIndex, HashEmbedder, LocalEndpointEmbedder, build_index, library_index, main

FIX = Path(__file__).parent / "fixtures" / "bim_assets"


@pytest.fixture()
def index_path(tmp_path: Path) -> Path:
    out = tmp_path / "_index" / "sketchup-assets.sqlite"
    meta = build_index([FIX], out, recipe_dir=FIX / "recipes")
    assert meta["counts"]["cards"] == 7
    assert meta["embedding_model"] == HashEmbedder.model
    return out


def test_graph_edges(index_path: Path) -> None:
    idx = AssetIndex(index_path)
    rels = idx.meta["counts"]["by_rel"]
    for rel in ("instance_of", "in_class", "maps_to_ifc", "uses_material", "on_level", "made_by", "contains"):
        assert rels.get(rel), rel
    edges = {(r[0], r[1], r[2]) for r in idx.con.execute("SELECT src, rel, dst FROM edge")}
    assert ("su-inst:demo:10@0", "contains", "su-inst:demo:11@1") in edges
    assert ("su-def:demo:t1", "contains", "su-def:demo:c1") in edges
    assert ("su-inst:demo:11@1", "instance_of", "su-def:demo:c1") in edges


def test_glass_railing_dimension_query(index_path: Path) -> None:
    res = AssetIndex(index_path).search("유리난간 1.2m", k=3)
    assert res["dims_mm"] == [1200.0]
    top = res["results"][0]
    assert top["id"] == "su-def:demo:g1"
    assert "dims" in top["channels"]
    assert top["asset_file"].endswith("objects/glass-railing/유리패널A.skp")
    kinds = {(c["rel"], c["kind"]) for c in top["context"]}
    assert {("made_by", "recipe"), ("maps_to_ifc", "ifc"), ("uses_material", "material")} <= kinds


def test_cafe_chair_hides_parts_inside_blocks(index_path: Path) -> None:
    res = AssetIndex(index_path).search("카페 의자", k=10)
    ids = [r["id"] for r in res["results"]]
    assert ids[0] in {"su-def:demo:c1", "su-def:demo:t1", "su-inst:demo:10@0"}
    assert "su-inst:demo:11@1" not in ids
    res = AssetIndex(index_path).search("카페 의자", k=10, include_inside_block=True)
    assert "su-inst:demo:11@1" in [r["id"] for r in res["results"]]


def test_build_is_deterministic(tmp_path: Path, index_path: Path) -> None:
    other = tmp_path / "b.sqlite"
    meta = build_index([FIX], other, recipe_dir=FIX / "recipes")
    assert meta == {**AssetIndex(index_path).meta}


def test_remote_embedding_endpoint_refused() -> None:
    with pytest.raises(ValueError):
        LocalEndpointEmbedder("https://api.example.com/v1", "BAAI/bge-m3")
    assert LocalEndpointEmbedder("http://127.0.0.1:8080", "BAAI/bge-m3").url.endswith("/v1/embeddings")


def test_cli_and_api(index_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["query", "옹벽 아니고 외벽", "--index", str(index_path), "-k", "2"]) == 0
    assert "su-def:demo:w1" in capsys.readouterr().out
    monkeypatch.setenv("SION_ASSET_INDEX", str(index_path))
    from sion_api.main import create_app

    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        r = c.get("/api/v1/graphrag/assets", params={"q": "유리난간 1.2m", "k": 2})
        assert r.status_code == 200, r.text
        assert r.json()["results"][0]["id"] == "su-def:demo:g1"
    monkeypatch.setenv("SION_ASSET_INDEX", str(index_path.parent / "missing.sqlite"))
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        assert c.get("/api/v1/graphrag/assets", params={"q": "x"}).status_code == 503


def test_library_index_for_place_block() -> None:
    lib = library_index([FIX])["demo"]
    assert lib["su-def:demo:g1"]["path"] == "objects/glass-railing/유리패널A.skp"
    assert lib["demo:furniture:카페체어"]["asset_id"] == "su-def:demo:c1"
    assert lib["demo:furniture:카페체어"]["block"] is True
    assert "su-inst:demo:11@1" not in lib  # part inside a block is not its own asset
