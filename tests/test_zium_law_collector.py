import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("c", ROOT / "scripts/ontology/collect_zium_law.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def test_build_from_fixtures(tmp_path):
    calls = tmp_path / "calls"
    calls.mkdir()
    (calls / "sp_site_compliance.out.json").write_text(json.dumps({"zone": "생산관리지역", "bcr_pct": 20, "far_pct": 80, "apiKey": "x"}), encoding="utf-8")
    (calls / "sp_site_compliance.args.json").write_text("{}", encoding="utf-8")
    tpl = tmp_path / "tpl" / "smoke"
    tpl.mkdir(parents=True)
    (tpl / "A.skp").write_bytes(b"1")
    exp = c.build(calls, tmp_path / "tpl", ROOT / "standards/zium/manifest.json")
    keys = {n["stable_key"] for n in exp["nodes"]}
    assert "finding:goyeon-1525:bcr" in keys and "standard:zium" in keys
    assert "apiKey" not in json.dumps(exp)
    for e in exp["edges"]:
        assert e["source_stable_key"] in keys and e["target_stable_key"] in keys
    assert c.jsonld(exp)["@graph"]
