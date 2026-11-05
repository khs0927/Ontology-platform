import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_loads_and_gaps_have_no_path():
    spec = importlib.util.spec_from_file_location("zc", ROOT / "scripts/standards/zium_check.py")
    zc = importlib.util.module_from_spec(spec); spec.loader.exec_module(zc)
    res = zc.check()
    assert set(res) >= {"cad", "revit", "sketchup"}
    for rows in res.values():
        for r in rows:
            assert (r["state"] == "gap") == (r["path"] is None)
