import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "assets" / "sketchup"
SCHEMA = json.loads((ROOT / "schemas" / "sion-bim-asset-1.schema.json").read_text(encoding="utf-8"))
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "number": (int, float), "null": type(None)}


def _validate(v, s, path="$"):
    errs = []
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: const")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: enum {v!r}")
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(isinstance(v, TYPES[t]) and not (t == "number" and isinstance(v, bool)) for t in ts):
            return [f"{path}: type"]
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: pattern")
        if len(v) < s.get("minLength", 0):
            errs.append(f"{path}: minLength")
    if isinstance(v, dict):
        errs += [f"{path}.{k}: required" for k in s.get("required", []) if k not in v]
        for k, sub in s.get("properties", {}).items():
            if k in v:
                errs += _validate(v[k], sub, f"{path}.{k}")
    if isinstance(v, list) and "items" in s:
        for i, it in enumerate(v):
            errs += _validate(it, s["items"], f"{path}[{i}]")
    return errs


def _cards():
    lines = (BASE / "0914-meeting" / "cards.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines]


def test_cards_validate_against_schema():
    errs = [e for c in _cards() for e in _validate(c, SCHEMA)]
    assert not errs, errs[:10]


def test_full_coverage():
    src = ROOT / "data" / "sources" / "sketchup" / "0914-meeting"
    dump = json.loads((src / "model_dump.json").read_text(encoding="utf-8"))
    hier = json.loads((src / "hierarchy.json").read_text(encoding="utf-8"))["nodes"]
    cards = _cards()
    guids = {c["source"]["guid"] for c in cards if c["card_kind"] == "definition"}
    occ = sorted(c["source"]["occurrence"] for c in cards if c["card_kind"] == "instance")
    assert guids == {d["guid"] for d in dump["definitions"]}
    assert occ == list(range(len(hier)))
    assert len(ids_all := {c["asset_id"] for c in cards}) == len(cards), "duplicate asset_id"
    assert ids_all
    ids = {c["asset_id"] for c in cards}
    assert all(c["definition_ref"] in ids for c in cards if c["card_kind"] == "instance")
    cov = json.loads((BASE / "0914-meeting" / "coverage.json").read_text(encoding="utf-8"))
    assert cov["coverage_pct"] == 100.0
    assert len(list((BASE / "0914-meeting" / "cards").glob("*.json"))) == len(cards)


def test_blocks_and_recipes():
    cards = _cards()
    for c in cards:
        if c["card_kind"] == "definition" and c["class"] in {"tree", "person", "furniture"}:
            assert c["block"], c["asset_id"]
        assert (ROOT / c["recipe"]["class_recipe"]).exists()
        assert c["review_state"] == "unverified"


def test_no_private_paths():
    bad = re.compile(r"[A-Za-z]:[\\/]+(Users|ProgramData)|AppData|내 드라이브", re.I)
    for p in BASE.rglob("*.json*"):
        assert not bad.search(p.read_text(encoding="utf-8")), p


def test_outputs_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sketchup" / "build_bim_cards.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
