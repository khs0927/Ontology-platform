"""SketchUp collection pipeline: manifest, preflight (runs in CI) and namespace scaffolding (#79)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sion_ingestion.sketchup_assets import DEFAULTS, REGISTRY_REL, SketchUpAssetError, load_registry
from sion_ingestion.sketchup_collection import (
    CONTENT_INDEX_REL,
    EXPLICIT_CLASS_CONFIDENCE,
    MANIFEST_SCHEMA_FILE,
    CollectionError,
    build_namespace,
    ingest,
    main,
    manifest_path,
    manifest_text,
    personal_paths,
    preflight,
    preflight_warnings,
    redact_personal_paths,
    scaffold,
    write_registry,
)

ROOT = Path(__file__).resolve().parents[1]
#: Synthetic Windows profile prefix, assembled at runtime so the public privacy scan does not flag it.
WIN_USERS = "C:" + "\\" + "Users"
NS = "0914-meeting"
NS_DIR = f"data/sources/sketchup/{NS}"
SHARED = [
    REGISTRY_REL,
    MANIFEST_SCHEMA_FILE,
    "data/sources/sketchup/object-classes.json",
    "docs/sketchup/MODELING-GUIDELINES.ko.md",
    "docs/sketchup/GROUPING-WORKFLOW.ko.md",
    "data/bootstrap/sketchup-0914-meeting.json",
    "data/bootstrap/sketchup-0914-meeting.ontology.json",
    CONTENT_INDEX_REL,
]


# --------------------------------------------------------------------------- the committed collection (CI gate)


def test_repository_preflight_is_clean():
    """Every registered namespace: hashes, encoding, personal paths, sizes, overlay, hierarchy order."""
    assert preflight() == []


def test_committed_manifest_is_current_and_pins_the_captures():
    path = manifest_path(NS)
    assert path.read_text(encoding="utf-8") == manifest_text(NS)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["model"]["sketchup_version"] == "25.0.634"
    assert manifest["model"]["skp_file"] == "0914_담당미팅.skp"
    assert manifest["dump_sha256"] == "b698c632b9396c37abb06f6f0f4a040a16066d953b22c39dd83acf6f1f674b7d"
    assert manifest["content_address"] == manifest["dump_sha256"]
    index = json.loads((ROOT / CONTENT_INDEX_REL).read_text(encoding="utf-8"))
    assert index["by_dump_sha256"][manifest["content_address"]]["namespace"] == NS
    assert index["by_dump_sha256"][manifest["content_address"]]["capture_set_sha256"] == manifest["capture_set_sha256"]
    assert set(manifest["probe_sha256"]) == {"geometry_probe", "grouping_probe"}
    assert all("sha256" in i for i in manifest["inputs"] if i["kind"] == "capture")
    assert {o["role"] for o in manifest["outputs"]} == {"graph-export", "ontology-export"}


def test_registry_is_data_and_drives_the_defaults(tmp_path):
    registry = load_registry()
    assert DEFAULTS[NS]["dump"] == ROOT / registry[NS]["dump"]
    assert DEFAULTS[NS]["output"] == ROOT / "data/bootstrap/sketchup-0914-meeting.json"
    write_registry(registry, tmp_path)  # the committed file is in the writer's canonical form
    assert (tmp_path / REGISTRY_REL).read_bytes() == (ROOT / REGISTRY_REL).read_bytes()
    assert b"\r" not in (tmp_path / REGISTRY_REL).read_bytes()  # LF on every OS (Windows CI)


def test_cli_preflight_with_build_check():
    completed = subprocess.run(
        [sys.executable, "-m", "sion_ingestion.sketchup_collection", "preflight", "--namespace", NS, "--build"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True and report["findings"] == []
    assert {w["check"] for w in report["warnings"]} == {"model-dirty"}  # pinned captures: dirty, not changed


def test_personal_path_detection_allows_generic_profiles():
    assert personal_paths(rb'"C:\\Users\\USER\\Documents\\a.skp"') == 0
    assert personal_paths(b"/Users/USER/x and /home/user/repo and %USERPROFILE%") == 0
    assert personal_paths(b"https://example.com/home/alice") == 0
    assert personal_paths(f'"{WIN_USERS}\\hong\\Desktop\\a.skp"'.encode()) == 1
    assert personal_paths(("D:/" + "Users/홍길동/a.skp").encode()) == 1
    assert personal_paths(b"/home/alice/a.json /Users/bob/b.json") == 2


# --------------------------------------------------------------------------- negative cases on a copied tree


@pytest.fixture(scope="module")
def base_tree(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("su-base")
    shutil.copytree(ROOT / NS_DIR, root / NS_DIR)
    for rel in SHARED:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, root / rel)
    return root


@pytest.fixture
def tree(base_tree, tmp_path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(base_tree, root)
    assert preflight(NS, root) == []
    return root


def _checks(root: Path, **kw) -> set[tuple[str, str]]:
    return {(f["check"], Path(f["path"].split(" ")[0]).name) for f in preflight(NS, root, **kw)}


def _edit_json(path: Path, fn) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def test_changed_capture_fails_hash_and_pin(tree):
    dump = tree / NS_DIR / "model_dump.json"
    dump.write_bytes(dump.read_bytes().replace(b'"25.0.634"', b'"25.0.635"', 1))
    checks = _checks(tree)
    assert ("hash", "model_dump.json") in checks


def test_personal_path_bom_and_binaries_are_rejected(tree):
    ns_dir = tree / NS_DIR
    _edit_json(ns_dir / "classification.json", lambda d: d.update(note=f"{WIN_USERS}\\hong\\Desktop\\0914.skp"))
    sup = ns_dir / "classification.supplement.json"
    sup.write_bytes(b"\xef\xbb\xbf" + sup.read_bytes())
    (ns_dir / "objects").mkdir()
    (ns_dir / "objects" / "wall.skp").write_bytes(b"SketchUp Model")
    (ns_dir / "render.png").write_bytes(b"\x89PNG")
    (ns_dir / "notes.json").write_text('{"src": "/home/alice/su"}', encoding="utf-8")
    checks = _checks(tree)
    assert ("personal-path", "classification.json") in checks
    assert ("encoding", "classification.supplement.json") in checks
    assert ("skp-binary", "wall.skp") in checks
    assert ("unlisted", "render.png") in checks and ("unlisted", "notes.json") in checks


def test_classifications_must_stay_unverified_candidates(tree):
    def approve(d):
        d["assignments"][0]["verification_state"] = "machine_verified"
        d["assignments"][1]["confidence"] = 1.0
        d["assignments"][2]["review"] = {"decision": "approve"}
        d["assignments"][3]["class"] = "no-such-class"

    _edit_json(tree / NS_DIR / "classification.json", approve)
    _edit_json(
        tree / NS_DIR / "classification.supplement.json",
        lambda d: d["assignments"][0].update(verification_state="human_verified"),
    )
    findings = [f for f in preflight(NS, tree) if f["check"] in {"candidate", "classification"}]
    locs = {(f["check"], f["path"].split(" ", 1)[1]) for f in findings}
    assert ("candidate", "$.assignments[0]") in locs and ("candidate", "$.assignments[1]") in locs
    assert ("candidate", "$.assignments[2]") in locs and ("classification", "$.assignments[3]") in locs
    assert any(f["path"].startswith(f"{NS_DIR}/classification.supplement.json") for f in findings)


def test_classification_must_pin_the_dump(tree):
    _edit_json(tree / NS_DIR / "classification.json", lambda d: d.pop("model_dump_sha256"))
    assert ("classification", "classification.json") in _checks(tree)
    _edit_json(tree / NS_DIR / "classification.json", lambda d: d.update(model_dump_sha256="0" * 64))
    assert ("classification", "classification.json") in _checks(tree)
    _edit_json(tree / NS_DIR / "classification.json", lambda d: d.update(schema="other/v1"))
    assert ("classification", "classification.json") in _checks(tree)


def test_probe_hierarchy_order_must_follow_the_dump(tree):
    def swap(d):
        d["nodes"][3], d["nodes"][4] = d["nodes"][4], d["nodes"][3]

    _edit_json(tree / NS_DIR / "grouping_probe.json", swap)
    _edit_json(tree / NS_DIR / "hierarchy.json", swap)
    checks = _checks(tree)
    assert ("hierarchy-order", "grouping_probe.json") in checks
    assert ("hierarchy-order", "hierarchy.json") in checks
    assert ("hash", "grouping_probe.json") in checks


def test_size_limits_and_manifest_schema(tree):
    _edit_json(manifest_path(NS, tree), lambda d: d["limits"].update(max_input_bytes=100_000, max_output_bytes=1))
    checks = _checks(tree)
    assert ("size", "model_dump.json") in checks and ("size", "sketchup-0914-meeting.json") in checks
    assert ("size", "openings.json") not in checks
    _edit_json(manifest_path(NS, tree), lambda d: d["inputs"].append({"path": "../outside.json", "role": "x"}))
    assert {f["check"] for f in preflight(NS, tree)} == {"manifest-schema"}


def test_build_option_detects_a_stale_export(tree):
    out = tree / "data/bootstrap/sketchup-0914-meeting.json"
    # evidence paths are repo-relative, so a copied tree regenerates its own (still deterministic) export
    out.write_text(build_namespace(NS, tree), encoding="utf-8")
    assert preflight(NS, tree, build=True) == []
    out.write_text(out.read_text(encoding="utf-8").replace("0914", "0915", 1), encoding="utf-8")
    assert ("build", "sketchup-0914-meeting.json") in _checks(tree, build=True)


# --------------------------------------------------------------------------- scaffolding a new namespace


@pytest.fixture
def fresh_root(tmp_path) -> tuple[Path, Path]:
    """A repo with only the shared inputs, plus a SketchUp export folder (0914 captures as a stand-in)."""
    root = tmp_path / "repo"
    for rel in SHARED[1:5]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, root / rel)
    export = tmp_path / "su-export"
    export.mkdir()
    shutil.copyfile(ROOT / NS_DIR / "model_dump.json", export / "model_dump.json")
    shutil.copyfile(ROOT / NS_DIR / "geometry_probe.json", export / "geom_probe.json")  # geom_probe.rb name
    shutil.copyfile(ROOT / NS_DIR / "grouping_probe.json", export / "grouping_probe.json")
    (export / "view_iso.png").write_bytes(b"\x89PNG")  # renders are never copied
    (export / "model.skp").write_bytes(b"SketchUp Model")
    return root, export


def test_scaffold_registers_builds_checks_and_emits_a_test(fresh_root):
    root, export = fresh_root
    result = scaffold("fixture-model", root, from_dir=export, grouping_doc="docs/sketchup/GROUPING-WORKFLOW.ko.md")
    assert result["ok"], result["preflight"]
    ns_dir = root / "data/sources/sketchup/fixture-model"
    assert sorted(p.name for p in ns_dir.iterdir()) == [
        "classification.json",
        "geometry_probe.json",
        "grouping_probe.json",
        "manifest.json",
        "model_dump.json",
    ]
    entry = load_registry(root)["fixture-model"]
    assert (
        entry["probe"].endswith("/geometry_probe.json")
        and entry["output"] == "data/bootstrap/sketchup-fixture-model.json"
    )
    overlay = json.loads((ns_dir / "classification.json").read_text(encoding="utf-8"))
    manifest = json.loads((ns_dir / "manifest.json").read_text(encoding="utf-8"))
    assert overlay["assignments"] == [] and overlay["model_dump_sha256"] == manifest["dump_sha256"]
    assert manifest["namespace"] == "fixture-model" and manifest["model"]["sketchup_version"] == "25.0.634"
    out = root / entry["output"]
    assert out.read_text(encoding="utf-8") == build_namespace("fixture-model", root)
    export_json = json.loads(out.read_text(encoding="utf-8"))
    assert export_json["source"].startswith("sketchup-assets:fixture-model:")
    candidates = [e for e in export_json["edges"] if e["properties"].get("candidate")]
    assert candidates and all(e["verification_state"] == "unverified" for e in candidates)
    stub = root / "tests/test_sketchup_ns_fixture_model.py"
    compile(stub.read_text(encoding="utf-8"), str(stub), "exec")
    assert manifest["dump_sha256"] in stub.read_text(encoding="utf-8")

    # idempotent: re-running changes nothing but rebuilds and re-checks
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    again = scaffold("fixture-model", root, from_dir=export, grouping_doc="docs/sketchup/GROUPING-WORKFLOW.ko.md")
    assert again["ok"] and not any(a.startswith(("copied", "registered", "wrote tests")) for a in again["actions"])
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_scaffold_refuses_bad_input(fresh_root, tmp_path):
    root, export = fresh_root
    with pytest.raises(CollectionError, match="must match"):
        scaffold("Bad Name", root, from_dir=export)
    with pytest.raises(CollectionError, match="model_dump.json is missing"):
        scaffold("empty-model", root)
    scaffold("fixture-model", root, from_dir=export, write_test=False)
    changed = tmp_path / "changed"
    changed.mkdir()
    dump = (export / "model_dump.json").read_bytes().replace(b'"25.0.634"', b'"25.0.635"', 1)
    (changed / "model_dump.json").write_bytes(dump)
    with pytest.raises(CollectionError, match="differs"):
        scaffold("fixture-model", root, from_dir=changed)
    with pytest.raises(CollectionError, match="already registered differently"):
        scaffold("fixture-model", root, guidelines="data/sources/sketchup/object-classes.json")


def _tree(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_scaffold_failed_build_leaves_nothing_behind(fresh_root):
    """A build failure (default guidelines citing another model) must not register a broken namespace."""
    root, export = fresh_root
    default_guide = root / "docs/sketchup/MODELING-GUIDELINES.ko.md"
    fixed_guide = root / "docs/sketchup/OTHER-MODEL-GUIDELINES.ko.md"
    fixed_guide.write_bytes(default_guide.read_bytes())
    default_guide.write_text(
        default_guide.read_text(encoding="utf-8")
        + '\n## Other model\n\n<!-- sion-guide id="other" evidence="def:NoSuchDefinition" -->\n\ntext\n',
        encoding="utf-8",
    )
    before = _tree(root)
    with pytest.raises(CollectionError, match="build failed: .*cites unknown definition NoSuchDefinition"):
        scaffold("other-model", root, from_dir=export)
    assert _tree(root) == before
    assert not (root / "data/sources/sketchup/other-model").exists()
    assert "other-model" not in load_registry(root)

    # the suggested fix (--guidelines written for this model) works without --force
    result = scaffold("other-model", root, from_dir=export, guidelines="docs/sketchup/OTHER-MODEL-GUIDELINES.ko.md")
    assert result["ok"], result["preflight"]
    assert load_registry(root)["other-model"]["guidelines"] == "docs/sketchup/OTHER-MODEL-GUIDELINES.ko.md"
    assert preflight("other-model", root) == []


def test_scaffold_failed_preflight_leaves_nothing_behind(fresh_root):
    root, export = fresh_root
    namespace = root / "data/sources/sketchup/fixture-model"
    namespace.mkdir(parents=True)
    (namespace / "model.skp").write_bytes(b"SketchUp Model")
    before = _tree(root)

    result = scaffold("fixture-model", root, from_dir=export)

    assert not result["ok"]
    assert result["actions"] == []
    assert any(f["check"] == "skp-binary" for f in result["preflight"])
    assert _tree(root) == before


def test_scaffold_refuses_symlinked_output(fresh_root, tmp_path):
    root, export = fresh_root
    outside = tmp_path / "outside"
    outside.mkdir()
    output_dir = root / "data/bootstrap"
    try:
        output_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    before = _tree(root)

    with pytest.raises(CollectionError, match="output must be a direct path"):
        scaffold("fixture-model", root, from_dir=export)

    assert _tree(root) == before
    assert list(outside.iterdir()) == []


def test_scaffold_replaces_an_unbuilt_registry_entry_without_force(fresh_root):
    root, export = fresh_root
    entry = {
        "dump": "data/sources/sketchup/half-model/model_dump.json",
        "classes": "data/sources/sketchup/object-classes.json",
        "classification": "data/sources/sketchup/half-model/classification.json",
        "guidelines": "docs/sketchup/GROUPING-WORKFLOW.ko.md",
        "output": "data/bootstrap/sketchup-half-model.json",
    }
    write_registry({"half-model": entry}, root)  # left over by an older failed run: no manifest, no export
    result = scaffold("half-model", root, from_dir=export, write_test=False)
    assert result["ok"], result["preflight"]
    assert load_registry(root)["half-model"]["guidelines"] == "docs/sketchup/MODELING-GUIDELINES.ko.md"


def test_scaffold_validates_before_writing(fresh_root):
    root, export = fresh_root
    before = _tree(root)
    with pytest.raises(CollectionError, match="model_dump.json is missing"):
        scaffold("typo-name", root)
    assert not (root / "data/sources/sketchup/typo-name").exists()
    for kwargs in (
        {"guidelines": "/etc/passwd"},
        {"guidelines": "../outside.md"},
        {"classes": "C:\\data\\classes.json"},
        {"grouping_doc": "docs/../../x.md"},
    ):
        with pytest.raises(CollectionError, match="repo-relative"):
            scaffold("typo-name", root, from_dir=export, **kwargs)
    with pytest.raises(CollectionError, match="does not exist"):
        scaffold("typo-name", root, from_dir=export, guidelines="docs/sketchup/missing.md")
    assert _tree(root) == before
    assert not (root / "data/sources/sketchup/typo-name").exists()


def test_redact_personal_paths_keeps_generic_profiles_and_the_filename():
    payload = {
        "path": WIN_USERS + "\\hong\\Desktop\\fixture.skp",
        "note": "/" + "home/alice/secret.skp",
        "ok": WIN_USERS + "\\USER\\a.skp",
    }
    redacted, count = redact_personal_paths(json.dumps(payload).encode())
    parsed = json.loads(redacted)
    assert count == 2
    assert parsed["path"] == "<redacted>/fixture.skp"
    assert parsed["note"] == "<redacted>/secret.skp"
    assert "USER" in parsed["ok"] and "hong" not in redacted.decode()
    assert personal_paths(redacted) == 0
    again, again_count = redact_personal_paths(redacted)
    assert again == redacted and again_count == 0


def _synthetic_dump(*, modified: bool = False, object_class: str = "retaining-wall", conflict: bool = False) -> dict:
    """Public synthetic capture. A class is present only as an explicit attribute value."""
    attributes: dict = {"sion": {"object_class": object_class}}
    if conflict:
        attributes["sion"]["su_class"] = "paving"
    return {
        "_meta": {
            "tool": "synthetic-fixture",
            "sketchup_version": "0",
            "dumped_at": "2026-01-01 00:00:00 +0000",
            "length_unit": "mm",
            "area_unit": "m2",
        },
        "model": {
            "title": "fixture",
            "path": WIN_USERS + "\\hong\\Desktop\\fixture.skp",
            "description": "",
            "modified": modified,
            "georeferenced": False,
            "units_options": {"LengthUnit": 2, "LengthPrecision": 0, "SnapAngle": 15.0},
            "shadow_info": {"City": "Seoul", "Country": "KR", "Latitude": 0, "Longitude": 0},
            "bounds": {"min": [0, 0, 0], "max": [1000, 200, 300], "size": [1000, 200, 300]},
            "top_level_count": 1,
            "top_level_types": {"ComponentInstance": 1},
            "definitions_count": 2,
            "layers_count": 1,
            "materials_count": 0,
            "pages_count": 0,
            "styles_count": 0,
        },
        "styles": [],
        "pages": [],
        "selected_page": None,
        "layer_folders": [],
        "layers": [
            {
                "name": "Layer0",
                "visible": True,
                "color": [0, 0, 0, 255],
                "line_style": None,
                "usage_by_type": {},
                "usage_total": 0,
            }
        ],
        "materials": [],
        "definitions": [
            {
                "name": "wall-a",
                "guid": "00000000-0000-4000-8000-000000000001",
                "description": "",
                "kind": "component",
                "instances": 1,
                "used_instances": 1,
                "bounds_size": [1000, 200, 300],
                "entity_counts": {"Face": 6, "Edge": 12},
                "face_area_m2": 1.0,
                "child_definitions": {},
                "layers_used": {"Layer0": 18},
                "materials_used": {},
                "instance_layers": {"Layer0": 1},
                "attributes": attributes,
            },
            {
                "name": "retaining-wall",
                "guid": "00000000-0000-4000-8000-000000000002",
                "description": "/" + "home/alice/secret.skp",
                "kind": "component",
                "instances": 0,
                "used_instances": 0,
                "bounds_size": [1, 1, 1],
                "entity_counts": {"Face": 0, "Edge": 0},
                "face_area_m2": 0,
                "child_definitions": {},
                "layers_used": {},
                "materials_used": {},
                "attributes": {"note": "retaining-wall"},
            },
        ],
        "hierarchy": [
            {
                "pid": 1,
                "depth": 0,
                "type": "ComponentInstance",
                "name": "",
                "definition": "wall-a",
                "path": "wall-a",
                "layer": "Layer0",
                "material": None,
                "transform": {"origin": [0, 0, 0], "scale": [1, 1, 1], "rot_z_deg": 0},
                "world_bounds": {"min": [0, 0, 0], "max": [1000, 200, 300], "size": [1000, 200, 300]},
                "child_counts": {},
            }
        ],
    }


def _grouping(modified: bool) -> dict:
    return {
        "_meta": {"tool": "synthetic-fixture", "dumped_at": "2026-01-01 00:00:00 +0000", "model": "fixture"},
        "model_modified": modified,
        "active_path": [],
        "nodes": [
            {
                "pid_path": [1],
                "depth": 0,
                "definition": "wall-a",
                "local_identity": True,
                "local_origin": [0, 0, 0],
                "local_xaxis": [1, 0, 0],
                "mirrored": False,
                "locked": False,
                "hidden": False,
                "glued_to": None,
            }
        ],
        "definitions": [
            {
                "name": "wall-a",
                "kind": "component",
                "count_instances": 1,
                "raw_geometry_by_layer": {"Face": {"Layer0": 6}},
                "child_instances_by_layer": {},
                "bounds_min": [0, 0, 0],
                "insertion_point": [0, 0, 0],
                "behavior": {"cuts_opening": False},
            }
        ],
    }


def _ingest_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    classes = ROOT / "data/sources/sketchup/object-classes.json"
    (root / "data/sources/sketchup").mkdir(parents=True)
    shutil.copyfile(classes, root / "data/sources/sketchup/object-classes.json")
    guide = root / "docs/sketchup/FIXTURE.ko.md"
    guide.parent.mkdir(parents=True)
    guide.write_text(
        "\n".join(
            [
                "## Fixture",
                "",
                '<!-- sion-guide id="fixture" order="1" kind="guideline" '
                'applies_to="retaining-wall" evidence="def:wall-a" tools="sketchup-mcp2.get_model_info" -->',
                "",
                "Public synthetic fixture. Numbers come from the dump.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


def _write_export(directory: Path, dump: dict, *, modified_probe: bool | None = None) -> None:
    directory.mkdir()
    raw = json.dumps(dump).encode()
    (directory / "model_dump.json").write_bytes(b"\xef\xbb\xbf" + raw)
    if modified_probe is not None:
        (directory / "grouping_probe.json").write_bytes(json.dumps(_grouping(modified_probe)).encode())
    (directory / "model.skp").write_bytes(b"SketchUp Model")
    (directory / "view_iso.png").write_bytes(b"\x89PNG")


def test_ingest_is_idempotent_content_addressed_and_unverified(tmp_path):
    root = _ingest_root(tmp_path)
    export = tmp_path / "export"
    _write_export(export, _synthetic_dump(), modified_probe=False)
    result = ingest(
        "fixture-wall",
        root,
        from_dir=export,
        guidelines="docs/sketchup/FIXTURE.ko.md",
        write_test=False,
    )
    assert result["ok"], result["preflight"]
    assert result["personal_paths_redacted"] == 2
    ns_dir = root / "data/sources/sketchup/fixture-wall"
    assert not any(p.suffix.lower() in {".skp", ".png"} for p in ns_dir.rglob("*"))
    dump_bytes = (ns_dir / "model_dump.json").read_bytes()
    assert not dump_bytes.startswith(b"\xef\xbb\xbf")
    assert personal_paths(dump_bytes) == 0
    assert b"hong" not in dump_bytes and b"<redacted>/fixture.skp" in dump_bytes
    overlay = json.loads((ns_dir / "classification.json").read_text(encoding="utf-8"))
    assert overlay["model_dump_sha256"] == result["content_address"]
    assert [a["definition"] for a in overlay["assignments"]] == ["wall-a"]
    assignment = overlay["assignments"][0]
    assert assignment["class"] == "retaining-wall"
    assert assignment["confidence"] == EXPLICIT_CLASS_CONFIDENCE
    assert assignment["verification_state"] == "unverified" and assignment["source_kind"] == "inferred"
    assert assignment["evidence_locator"] == "$.definitions[0].attributes.sion.object_class"
    assert assignment["evidence_sha256"] == result["content_address"]
    assert "retaining-wall" not in {a["definition"] for a in overlay["assignments"][1:]}
    manifest = json.loads((ns_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["content_address"] == result["content_address"] == manifest["dump_sha256"]
    assert manifest["model"]["modified"] is False and manifest["model"]["skp_file"] == "fixture.skp"
    index = json.loads((root / CONTENT_INDEX_REL).read_text(encoding="utf-8"))
    assert index["by_dump_sha256"][result["content_address"]]["namespace"] == "fixture-wall"
    export_json = json.loads((root / "data/bootstrap/sketchup-fixture-wall.json").read_text(encoding="utf-8"))
    edge = next(e for e in export_json["edges"] if e["properties"].get("predicate") == "classified_as" and e["properties"].get("candidate"))
    assert edge["verification_state"] == "unverified" and edge["confidence"] == EXPLICIT_CLASS_CONFIDENCE
    assert edge["properties"]["su_evidence"]["locator"] == assignment["evidence_locator"]
    assert edge["properties"]["su_evidence"]["source_sha256"] == result["content_address"]
    from sion_graphrag.projection import BASE_RELATION_WEIGHT, relation_weight

    assert relation_weight(edge["confidence"], edge["verification_state"], edge["properties"]) == BASE_RELATION_WEIGHT
    assert preflight("fixture-wall", root) == []

    before = _tree(root)
    again = ingest(
        "fixture-wall",
        root,
        from_dir=export,
        guidelines="docs/sketchup/FIXTURE.ko.md",
        write_test=False,
    )
    assert again["ok"] and again["content_address"] == result["content_address"]
    assert _tree(root) == before

    with pytest.raises(CollectionError, match="already ingested"):
        ingest("other-wall", root, from_dir=export, guidelines="docs/sketchup/FIXTURE.ko.md", write_test=False)
    assert _tree(root) == before


def test_ingest_refuses_unknown_or_conflicting_labels_without_writing(tmp_path):
    root = _ingest_root(tmp_path)
    export = tmp_path / "export"
    _write_export(export, _synthetic_dump(object_class="not-a-class"), modified_probe=False)
    before = _tree(root)
    with pytest.raises(CollectionError, match="not an object-class id"):
        ingest("fixture-wall", root, from_dir=export, guidelines="docs/sketchup/FIXTURE.ko.md", write_test=False)
    assert _tree(root) == before

    conflict = tmp_path / "conflict"
    _write_export(conflict, _synthetic_dump(conflict=True), modified_probe=False)
    with pytest.raises(CollectionError, match="conflicting class attributes"):
        ingest("fixture-wall", root, from_dir=conflict, guidelines="docs/sketchup/FIXTURE.ko.md", write_test=False)
    assert _tree(root) == before


def test_ingest_refuses_a_capture_that_changed_the_model(tmp_path):
    root = _ingest_root(tmp_path)
    export = tmp_path / "export"
    _write_export(export, _synthetic_dump(modified=False), modified_probe=True)
    before = _tree(root)
    with pytest.raises(CollectionError, match="model_modified disagrees"):
        ingest("fixture-wall", root, from_dir=export, guidelines="docs/sketchup/FIXTURE.ko.md", write_test=False)
    assert _tree(root) == before
    assert not (root / "data/sources/sketchup/fixture-wall").exists()


def test_ingest_cli_on_a_synthetic_export(tmp_path):
    root = _ingest_root(tmp_path)
    export = tmp_path / "export"
    _write_export(export, _synthetic_dump(), modified_probe=False)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sion_ingestion.sketchup_collection",
            "ingest",
            "--namespace",
            "fixture-wall",
            "--from-dir",
            str(export),
            "--root",
            str(root),
            "--guidelines",
            "docs/sketchup/FIXTURE.ko.md",
            "--no-test",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=root,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] and payload["classifications"] == 1
    assert preflight("fixture-wall", root) == []


def test_capture_that_changed_the_model_fails(tree):
    ns_dir = tree / NS_DIR
    _edit_json(ns_dir / "hierarchy.json", lambda d: d.update(modified_before=False, modified_after=True))
    _edit_json(ns_dir / "model_dump.json", lambda d: d["model"].update(modified_before=False, modified_after=True))
    _edit_json(ns_dir / "grouping_probe.json", lambda d: d.update(modified_before=False, modified_after=False))
    checks = _checks(tree)
    assert ("model-modified", "hierarchy.json") in checks and ("model-modified", "model_dump.json") in checks
    assert ("model-modified", "grouping_probe.json") not in checks
    _edit_json(ns_dir / "hierarchy.json", lambda d: d.update(modified_before=True, modified_after=True))
    assert ("model-modified", "hierarchy.json") not in _checks(tree)  # already dirty: a warning, not a failure


def test_geometry_probe_meta_participates_in_model_modified(tree):
    """geom_probe.rb stores the pair in ``_meta``; ``_meta`` is not a probed definition (#115 follow-up B)."""
    ns_dir = tree / NS_DIR
    probe = ns_dir / "geometry_probe.json"
    _edit_json(probe, lambda d: d.update(
        _meta={"tool": "grokbot read-only geometry probe v1", "modified_before": False, "modified_after": True}))
    checks = _checks(tree)
    assert ("model-modified", "geometry_probe.json") in checks
    assert ("hierarchy-order", "geometry_probe.json") not in checks

    _edit_json(probe, lambda d: d["_meta"].update(modified_before=True, modified_after=True))
    assert "geometry_probe.json" in {Path(w["path"]).name for w in preflight_warnings(NS, tree)}
    assert ("model-modified", "geometry_probe.json") not in _checks(tree)  # already dirty: a warning only


def test_producer_scripts_record_the_model_state_pair():
    """Ruby cannot run here or in CI, so pin the capture contract each producer script must write."""
    scripts = ROOT / "scripts/sketchup"
    for name in ("dump_model.rb", "geom_probe.rb", "grouping_probe.rb", "export_objects.rb"):
        text = (scripts / name).read_text(encoding="utf-8")
        assert "modified_before" in text and "modified_after" in text, name
    export = (scripts / "export_objects.rb").read_text(encoding="utf-8")
    assert export.index("objects.json") < export.index("hierarchy.json")  # hierarchy written after the export


def test_dirty_model_capture_is_a_warning(tree):
    ns_dir = tree / NS_DIR
    warned = {Path(w["path"]).name for w in preflight_warnings(NS, tree)}
    assert {"model_dump.json", "grouping_probe.json", "hierarchy.json"} <= warned  # legacy keys count too
    assert all(w["severity"] == "warning" for w in preflight_warnings(NS, tree))
    for name in ("model_dump.json", "grouping_probe.json", "hierarchy.json"):

        def clean(d, name=name):
            target = d["model"] if name == "model_dump.json" else d
            target.update(modified_before=False, modified_after=False)

        _edit_json(ns_dir / name, clean)
    assert preflight_warnings(NS, tree) == []
    assert not {c for c, _ in _checks(tree)} & {"model-dirty", "model-modified"}


def test_supplement_candidates_need_an_evidence_locator(tree):
    def strip(d):
        d["assignments"][0].pop("hierarchy_locator")
        d["assignments"][1]["hierarchy_locator"] = " "

    _edit_json(tree / NS_DIR / "classification.supplement.json", strip)
    locs = {f["path"].split(" ", 1)[1] for f in preflight(NS, tree) if "hierarchy_locator" in f["message"]}
    assert locs == {"$.assignments[0]", "$.assignments[1]"}


def test_v1_classification_overlay_does_not_require_a_locator(tree):
    _edit_json(tree / NS_DIR / "classification.json", lambda d: d["assignments"][0].pop("hierarchy_locator", None))
    assert not [f for f in preflight(NS, tree) if "hierarchy_locator" in f["message"]]


def test_preflight_cli_prints_findings_when_the_registry_cannot_load(monkeypatch, capsys):
    import sion_ingestion.sketchup_collection as collection

    def broken(root=collection.ROOT):
        raise SketchUpAssetError("registry schema rejected")

    monkeypatch.setattr(collection, "load_registry", broken)
    assert main(["preflight"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and report["warnings"] == []
    assert any(f["check"] == "registry" for f in report["findings"])
