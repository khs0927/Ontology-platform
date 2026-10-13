"""Generators listed in recipes.json must match files and the playbook recipe classes."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "sketchup" / "generators"
PLAYBOOK = ROOT / "docs" / "sketchup" / "BIM-ASSET-PLAYBOOK.ko.md"


def _recipes():
    return json.loads((GEN / "recipes.json").read_text(encoding="utf-8"))["generators"]


def test_each_generator_file_defines_its_method():
    for cls, fn in _recipes().items():
        src = (GEN / f"{fn}.rb").read_text(encoding="utf-8")
        assert re.search(rf"def {fn}\(", src), (cls, fn)
        assert "stamp(" in src, fn


def test_no_orphan_generator_files():
    files = {p.stem for p in GEN.glob("*.rb")} - {"sion_bim_common"}
    assert files == set(_recipes().values())


def test_playbook_recipe_table_matches():
    text = PLAYBOOK.read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([a-z-]+) \| `([a-z_]+)` \|", text, re.M)
    assert dict(rows) == _recipes()


def test_classes_in_common_map():
    common = (GEN / "sion_bim_common.rb").read_text(encoding="utf-8")
    for cls in _recipes():
        assert f"'{cls}'" in common, cls
    assert "DICT = 'sion_bim'" in common
