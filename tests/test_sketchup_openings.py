"""House openings: window / fire-entry-window / louver cards carry sion-bim-opening/1 params."""
import json
from pathlib import Path

from test_sketchup_bim_cards import TYPES, _cards, _validate

TYPES.setdefault("integer", int)

ROOT = Path(__file__).resolve().parents[1]
OPEN_SCHEMA = json.loads((ROOT / "schemas" / "sion-bim-opening-1.schema.json").read_text(encoding="utf-8"))
CODE = json.loads((ROOT / "data/sources/sketchup/code-refs/kr-fire-entry-window.json").read_text(encoding="utf-8"))


def _openings():
    return [c for c in _cards() if c.get("opening")]


def test_opening_blocks_validate():
    ops = _openings()
    assert ops
    errs = [e for c in ops for e in _validate(c["opening"], OPEN_SCHEMA)]
    assert not errs, errs[:10]


def test_subclasses_present_and_split():
    cls = {c["class"] for c in _openings()}
    assert {"window", "fire-entry-window", "louver"} <= cls
    subs = json.loads((ROOT / "data/sources/sketchup/object-subclasses.json").read_text(encoding="utf-8"))["subclasses"]
    assert {s["id"] for s in subs} == {"window", "fire-entry-window", "louver"}
    assert all(s["parent"] == "window-louver" for s in subs)


def test_fire_entry_window_flag_and_unverified_compliance():
    fe = [c for c in _openings() if c["class"] == "fire-entry-window"]
    assert fe
    for c in fe:
        o = c["opening"]
        assert o["fire_entry"]["is_fire_entry_window"] is True
        assert o["compliance"]["review_state"] == "unverified"
        assert o["compliance"]["status"] in {"pass-estimated", "fail-estimated", "needs-check"}
        assert {x["check"] for x in o["compliance"]["checks"]} >= {"glass_width", "glass_height", "sill", "marking_triangle"}


def test_code_ref_numbers_match_rule_text():
    items = {i["check"]: i for r in CODE["refs"] for i in r.get("items", [])}
    p = items["size_and_sill"]["params"]
    assert (p["glass_width_min_mm"], p["glass_height_min_mm"], p["sill_max_mm"], p["sill_max_balcony_mm"]) == (900, 1000, 800, 1200)
    assert items["marking_triangle"]["params"]["triangle_min_mm"] == 200


def test_louver_params():
    lv = [c for c in _openings() if c["opening"]["role"] == "louver-assembly"]
    assert lv and lv[0]["ifc"]["entity"] == "IfcShadingDevice"
    lp = lv[0]["opening"]["louver"]
    assert lp["direction"] == "horizontal" and lp["pitch_mm"] > 0 and lp["blade_count"] > 0


def test_no_local_paths_in_openings():
    txt = (ROOT / "data/sources/sketchup/0914-meeting/openings.json").read_text(encoding="utf-8")
    assert "C:/" not in txt and "Users" not in txt
