"""SketchUp model collection pipeline: manifest, preflight and namespace scaffolding.

Every collected SketchUp model lives in one *namespace*:

* ``data/sources/sketchup/<namespace>/`` holds the read-only captures (``model_dump.json``,
  ``geometry_probe.json``, ``grouping_probe.json``, ``hierarchy.json``, ...) and the authored
  overlays (``classification.json``, pinned to the dump SHA-256),
* ``data/sources/sketchup/<namespace>/manifest.json`` (``sion-sketchup-collection-manifest/v1``,
  JSON schema ``schemas/sion-sketchup-collection-manifest-1.schema.json``) records the model,
  SketchUp version, capture hashes, inputs and outputs,
* ``data/sources/sketchup/namespaces.json`` (``sion-sketchup-namespaces/v1``) registers the build
  inputs for :mod:`sion_ingestion.sketchup_assets`.

Commands::

    python -m sion_ingestion.sketchup_collection preflight [--namespace NS] [--build]
    python -m sion_ingestion.sketchup_collection manifest --namespace NS [--write | --check]
    python -m sion_ingestion.sketchup_collection scaffold --namespace NS [--from-dir DIR] [...]

The preflight never modifies anything. ``scaffold`` only writes the namespace's own files (copied
captures, an empty classification skeleton, the registry entry, the manifest, the generated export
and a regeneration test stub). It validates every input and builds the export in memory before it
registers anything, and it restores every file it wrote when a step fails. Classifications stay
``unverified`` candidates and are never approved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from sion_ingestion.sketchup_assets import (
    CLASSES_SCHEMA,
    CLASSIFICATION_SCHEMA,
    REGISTRY_REL,
    REGISTRY_SCHEMA,
    ROOT,
    SketchUpAssetError,
    _pid_paths,
    build_export,
    export_text,
    load_registry,
)

MANIFEST_SCHEMA = "sion-sketchup-collection-manifest/v1"
MANIFEST_SCHEMA_FILE = "schemas/sion-sketchup-collection-manifest-1.schema.json"
MANIFEST_NAME = "manifest.json"
SOURCES_REL = "data/sources/sketchup"
SUPPLEMENT_SCHEMA_PREFIX = "sion-sketchup-classification-supplement/"
#: Evidence locator every supplement candidate carries (scripts/sketchup/propose_supplement.py).
LOCATOR_KEY = "hierarchy_locator"
DEFAULT_LIMITS = {"max_input_bytes": 4 * 1024 * 1024, "max_output_bytes": 16 * 1024 * 1024}
NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
TEXT_SUFFIXES = {".json", ".md", ".txt", ".csv"}
BINARY_MODEL_SUFFIXES = {".skp", ".skb"}

#: Known per-namespace files: name -> (role, kind, producer).
KNOWN_FILES: dict[str, tuple[str, str, str | None]] = {
    "model_dump.json": ("dump", "capture", "scripts/sketchup/dump_model.rb"),
    "geometry_probe.json": ("geometry_probe", "capture", "scripts/sketchup/geom_probe.rb"),
    "grouping_probe.json": ("grouping_probe", "capture", "scripts/sketchup/grouping_probe.rb"),
    "hierarchy.json": ("hierarchy", "capture", "scripts/sketchup/export_objects.rb"),
    "objects.json": ("objects", "capture", "scripts/sketchup/export_objects.rb"),
    "objects_sha.json": ("objects_sha", "capture", "scripts/sketchup/export_objects.rb"),
    "openings.json": ("openings", "capture", None),
    "classification.json": ("classification", "authored", None),
    "classification.supplement.json": ("classification_supplement", "authored", None),
}
#: Export-folder file name -> committed file name (``geom_probe.rb`` writes ``geom_probe.json``).
CAPTURE_RENAMES = {"geom_probe.json": "geometry_probe.json"}
SHARED_DEFAULTS = {
    "classes": f"{SOURCES_REL}/object-classes.json",
    "guidelines": "docs/sketchup/MODELING-GUIDELINES.ko.md",
}
REVIEW_KEYS = {"approved", "approved_by", "review", "reviewed_by", "reviewer", "decision"}

# Personal absolute paths. Generic profile names (as in scripts/check_public_privacy.py) are allowed.
WIN_PROFILE_RE = re.compile(rb"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+([^\\/\s\"'`\r\n]+)", re.IGNORECASE)
NIX_PROFILE_RE = re.compile(rb"(?<![\w.~:-])/(?:home|Users)/([^/\s\"'`\\\r\n]+)")
GENERIC_PROFILE_NAMES = {b"user", b"username", b"public", b"example", b"shared", b"default", b"me"}


class CollectionError(ValueError):
    """The namespace cannot be scaffolded (bad name, missing dump, conflicting registry entry)."""


# --------------------------------------------------------------------------- helpers


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def _finding(namespace: str | None, check: str, path: str | None, message: str) -> dict[str, Any]:
    return {"namespace": namespace, "check": check, "path": path, "message": message}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_generic_profile(name: bytes) -> bool:
    low = name.lower()
    return low in GENERIC_PROFILE_NAMES or low[:1] in {b"<", b"%", b"$", b"{"}


def personal_paths(data: bytes) -> int:
    """Number of personal absolute paths (Windows profile dirs, ``/home/<name>``, ``/Users/<name>``)."""
    hits = 0
    for pattern in (WIN_PROFILE_RE, NIX_PROFILE_RE):
        hits += sum(1 for m in pattern.finditer(data) if not _is_generic_profile(m.group(1)))
    return hits


def namespace_dir(namespace: str, root: Path = ROOT) -> Path:
    return root / SOURCES_REL / namespace


def manifest_path(namespace: str, root: Path = ROOT) -> Path:
    return namespace_dir(namespace, root) / MANIFEST_NAME


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def registry_text(entries: dict[str, dict[str, str]]) -> str:
    """Deterministic ``namespaces.json`` text (namespaces and keys sorted)."""
    data = {
        "schema": REGISTRY_SCHEMA,
        "description": "SketchUp collection namespaces -> repo-relative build inputs/outputs for "
        "sion_ingestion.sketchup_assets. Edit with `python -m sion_ingestion.sketchup_collection scaffold`.",
        "namespaces": {ns: dict(sorted(entries[ns].items())) for ns in sorted(entries)},
    }
    return _json_text(data)


def write_registry(entries: dict[str, dict[str, str]], root: Path = ROOT) -> Path:
    """Write ``namespaces.json`` deterministically (namespaces and keys sorted)."""
    path = root / REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, not text mode: LF on every OS so the committed registry stays byte-identical on Windows.
    path.write_bytes(registry_text(entries).encode("utf-8"))
    return path


def namespace_build_paths(namespace: str, root: Path = ROOT) -> dict[str, Path]:
    entry = load_registry(root).get(namespace)
    if entry is None:
        raise CollectionError(f"namespace {namespace!r} is not registered in {REGISTRY_REL}")
    return {k: root / v for k, v in entry.items()}


def _build_entry(namespace: str, entry: dict[str, str], root: Path = ROOT) -> str:
    """Regenerate the export text from a registry entry (registered or only proposed)."""
    p = {k: root / v for k, v in entry.items()}
    export = build_export(
        p["dump"],
        p["classes"],
        p["classification"],
        p["guidelines"],
        namespace=namespace,
        probe_path=p.get("probe"),
        grouping_probe_path=p.get("grouping_probe"),
        grouping_doc_path=p.get("grouping_doc"),
    )
    return export_text(export)


def build_namespace(namespace: str, root: Path = ROOT) -> str:
    """Regenerate the ``sion-map-export/v1`` text for a registered namespace (no file is written)."""
    entry = load_registry(root).get(namespace)
    if entry is None:
        raise CollectionError(f"namespace {namespace!r} is not registered in {REGISTRY_REL}")
    return _build_entry(namespace, entry, root)


# --------------------------------------------------------------------------- manifest


def build_manifest(namespace: str, root: Path = ROOT) -> dict[str, Any]:
    """Manifest for a registered namespace from the files on disk (limits kept from the old manifest)."""
    entry = load_registry(root).get(namespace)
    if entry is None:
        raise CollectionError(f"namespace {namespace!r} is not registered in {REGISTRY_REL}")
    ns_dir = namespace_dir(namespace, root)
    old_path = manifest_path(namespace, root)
    limits = dict(DEFAULT_LIMITS)
    if old_path.exists():
        limits.update(_load_json(old_path).get("limits") or {})

    inputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in sorted(p for p in ns_dir.rglob("*") if p.is_file() and p.name != MANIFEST_NAME):
        rel = _rel(f, root)
        role, kind, producer = KNOWN_FILES.get(
            f.name, (re.sub(r"[^a-z0-9]+", "_", f.stem.lower()).strip("_"), "capture", None)
        )
        for key in ("probe", "grouping_probe", "classification", "dump"):
            if entry.get(key) == rel:
                role = {"probe": "geometry_probe"}.get(key, key)
        item: dict[str, Any] = {"path": rel, "role": role, "kind": kind}
        if kind == "capture":
            data = f.read_bytes()
            item["sha256"] = _sha256_bytes(data)
            item["bytes"] = len(data)
        if producer:
            item["producer"] = producer
        inputs.append(item)
        seen.add(rel)
    for key in ("classes", "guidelines", "grouping_doc", "dump", "probe", "grouping_probe", "classification"):
        rel = entry.get(key)
        if rel and rel not in seen:
            inputs.append({"path": rel, "role": key, "kind": "shared"})
            seen.add(rel)

    by_role = {i["role"]: i for i in inputs}
    dump_item = by_role.get("dump")
    if dump_item is None or "sha256" not in dump_item:
        raise CollectionError(f"{namespace}: the model dump must be a capture inside {_rel(ns_dir, root)}")
    dump = json.loads((root / dump_item["path"]).read_text(encoding="utf-8-sig"))
    model = dump.get("model", {})
    meta = dump.get("_meta", {})
    skp_file = Path(str(model.get("path") or model.get("title") or "").replace("\\", "/")).name

    outputs = [
        {
            "path": entry["output"],
            "role": "graph-export",
            "command": f"python -m sion_ingestion.sketchup_assets build --namespace {namespace}",
        }
    ]
    ontology = Path(entry["output"]).with_suffix(".ontology.json").as_posix()
    if (root / ontology).exists():
        outputs.append(
            {"path": ontology, "role": "ontology-export", "command": "python -m sion_ingestion.sketchup_ontology"}
        )

    return {
        "schema": MANIFEST_SCHEMA,
        "namespace": namespace,
        "model": {
            "skp_file": skp_file,
            "title": model.get("title", ""),
            "sketchup_version": str(meta.get("sketchup_version", "")),
            "dumped_at": meta.get("dumped_at"),
            "modified": model.get("modified"),
        },
        "dump_sha256": dump_item["sha256"],
        "probe_sha256": {i["role"]: i["sha256"] for i in inputs if i["role"].endswith("_probe") and "sha256" in i},
        "limits": limits,
        "inputs": inputs,
        "outputs": outputs,
    }


def manifest_text(namespace: str, root: Path = ROOT) -> str:
    return _json_text(build_manifest(namespace, root))


# --------------------------------------------------------------------------- preflight


def _schema_errors(manifest: Any, root: Path) -> list[str]:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema is a root dependency
        missing = {"schema", "namespace", "model", "dump_sha256", "inputs", "outputs"} - set(manifest)
        return [f"missing keys {sorted(missing)}"] if missing else []
    schema_file = root / MANIFEST_SCHEMA_FILE
    if not schema_file.exists():
        schema_file = ROOT / MANIFEST_SCHEMA_FILE
    validator = jsonschema.Draft202012Validator(_load_json(schema_file))
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '$'}: {e.message}"
        for e in sorted(validator.iter_errors(manifest), key=lambda e: list(map(str, e.absolute_path)))
    ]


def _check_text_file(ns: str, path: Path, rel: str, limit: int, out: list[dict[str, Any]]) -> bytes | None:
    if not path.exists():
        out.append(_finding(ns, "missing", rel, "file does not exist"))
        return None
    data = path.read_bytes()
    if len(data) > limit:
        out.append(_finding(ns, "size", rel, f"{len(data):,} bytes exceeds the {limit:,}-byte limit"))
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return data
    if data.startswith(b"\xef\xbb\xbf"):
        out.append(_finding(ns, "encoding", rel, "UTF-8 byte-order mark (write UTF-8 without BOM)"))
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        out.append(_finding(ns, "encoding", rel, f"not UTF-8 ({exc.reason} at byte {exc.start})"))
    hits = personal_paths(data)
    if hits:
        out.append(_finding(ns, "personal-path", rel, f"{hits} personal absolute path(s) (value withheld)"))
    return data


def _check_classification(
    ns: str, rel: str, data: dict[str, Any], dump_sha: str | None, dump: dict | None, classes: set[str] | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if data.get("schema") != CLASSIFICATION_SCHEMA:
        out.append(_finding(ns, "classification", rel, f"schema must be {CLASSIFICATION_SCHEMA}"))
    pinned = data.get("model_dump_sha256")
    if not pinned:
        out.append(_finding(ns, "classification", rel, "model_dump_sha256 is not pinned"))
    elif dump_sha and pinned != dump_sha:
        out.append(_finding(ns, "classification", rel, "model_dump_sha256 does not match the model dump"))
    assignments = data.get("assignments")
    if not isinstance(assignments, list):
        return [*out, _finding(ns, "classification", rel, "assignments must be a list")]
    def_names = {d["name"] for d in dump.get("definitions", [])} if dump else None
    seen: set[str] = set()
    for i, a in enumerate(assignments):
        loc = f"{rel} $.assignments[{i}]"
        missing = [k for k in ("definition", "class", "confidence", "basis_ko") if not a.get(k)]
        if missing:
            out.append(_finding(ns, "classification", loc, f"missing {missing}"))
            continue
        if a["definition"] in seen:
            out.append(_finding(ns, "classification", loc, "duplicate definition"))
        seen.add(a["definition"])
        if def_names is not None and a["definition"] not in def_names:
            out.append(_finding(ns, "classification", loc, "definition is not in the model dump"))
        if classes is not None and a["class"] not in classes:
            out.append(_finding(ns, "classification", loc, f"unknown class {a['class']!r}"))
        out.extend(_candidate_findings(ns, loc, a))
    return out


def _candidate_findings(ns: str, loc: str, a: dict[str, Any], *, locator: bool = False) -> list[dict[str, Any]]:
    """Classifications are inferred review candidates: never verified, approved or certain.

    ``locator``: the candidate must also cite its evidence (``hierarchy_locator``). Only the supplement
    schema carries one; the v1 classification overlay predates it.
    """
    out = []
    conf = a.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not 0 < conf < 1:
        out.append(_finding(ns, "candidate", loc, "confidence must be a number strictly between 0 and 1"))
    if locator and not (isinstance(a.get(LOCATOR_KEY), str) and a[LOCATOR_KEY].strip()):
        out.append(_finding(ns, "candidate", loc, f"{LOCATOR_KEY} (evidence locator) is required"))
    if a.get("verification_state", "unverified") != "unverified":
        out.append(_finding(ns, "candidate", loc, "verification_state must stay 'unverified' (approve on /review)"))
    if a.get("source_kind", "inferred") != "inferred":
        out.append(_finding(ns, "candidate", loc, "source_kind must be 'inferred'"))
    if REVIEW_KEYS & set(a):
        out.append(
            _finding(ns, "candidate", loc, f"review decision fields {sorted(REVIEW_KEYS & set(a))} are not allowed")
        )
    return out


def _check_order(ns: str, dump: dict, by_role: dict[str, tuple[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    hierarchy = dump.get("hierarchy") or []
    try:
        pid_paths = _pid_paths(hierarchy)
    except SketchUpAssetError as exc:
        return [_finding(ns, "hierarchy-order", None, f"model dump: {exc}")]
    dump_defs = {d["name"] for d in dump.get("definitions", [])}
    dump_pids = {n["pid"] for n in hierarchy}
    if "grouping_probe" in by_role:
        rel, gp = by_role["grouping_probe"]
        nodes = gp.get("nodes") or []
        if len(nodes) != len(hierarchy):
            out.append(_finding(ns, "hierarchy-order", rel, f"{len(nodes)} nodes, model dump has {len(hierarchy)}"))
        else:
            for i, (gn, pp, h) in enumerate(zip(nodes, pid_paths, hierarchy)):
                if gn.get("pid_path") != pp or gn.get("definition") != h["definition"]:
                    out.append(_finding(ns, "hierarchy-order", f"{rel} $.nodes[{i}]", "differs from the dump order"))
                    break
    if "hierarchy" in by_role:
        rel, hj = by_role["hierarchy"]
        seq = [(n.get("pid"), n.get("depth"), n.get("definition")) for n in hj.get("nodes") or []]
        ref = [(n["pid"], n["depth"], n["definition"]) for n in hierarchy]
        if len(seq) == len(ref):
            bad = next((i for i, (a, b) in enumerate(zip(seq, ref)) if a != b), None)
            if bad is not None:
                out.append(_finding(ns, "hierarchy-order", f"{rel} $.nodes[{bad}]", "differs from the dump order"))
        else:  # different depth caps: the shared persistent ids must keep the dump order
            common = {s[0] for s in seq} & dump_pids
            if [s[0] for s in seq if s[0] in common] != [r[0] for r in ref if r[0] in common]:
                out.append(_finding(ns, "hierarchy-order", rel, "shared persistent ids are not in dump order"))
        known = {s[0] for s in seq} | dump_pids
        if "objects" in by_role:
            orel, objs = by_role["objects"]
            stray = [o.get("pid") for o in objs.get("objects") or [] if o.get("pid") not in known]
            if stray:
                out.append(_finding(ns, "hierarchy-order", orel, f"{len(stray)} object(s) not in the hierarchy"))
    if "geometry_probe" in by_role:
        rel, probe = by_role["geometry_probe"]
        unknown = sorted(set(probe) - dump_defs) if isinstance(probe, dict) else []
        if unknown:
            out.append(_finding(ns, "hierarchy-order", rel, f"{len(unknown)} probed definition(s) not in the dump"))
    return out


def _modified_state(data: Any) -> tuple[Any, Any]:
    """(modified_before, modified_after) of a capture, top level or under ``model``; None when absent."""
    if not isinstance(data, dict):
        return None, None
    for d in (data, data.get("model")):
        if isinstance(d, dict) and ("modified_before" in d or "modified_after" in d):
            return d.get("modified_before"), d.get("modified_after")
    return None, None


def preflight_warnings(namespace: str, root: Path = ROOT) -> list[dict[str, Any]]:
    """Non-blocking findings (``severity: warning``): captures taken from an already-dirty model.

    Captures without ``modified_before`` fall back to the single legacy ``modified``/``model_modified`` value.
    """
    out: list[dict[str, Any]] = []
    for f in sorted(namespace_dir(namespace, root).glob("*.json")):
        if f.name == MANIFEST_NAME:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue  # preflight reports it
        before = _modified_state(data)[0]
        if before is None and isinstance(data, dict):
            model = data.get("model") if isinstance(data.get("model"), dict) else {}
            before = data.get("model_modified", model.get("modified"))
        if before is True:
            msg = "captured from a model with unsaved changes (modified_before is true)"
            out.append({**_finding(namespace, "model-dirty", _rel(f, root), msg), "severity": "warning"})
    return out


def preflight_namespace(namespace: str, root: Path = ROOT, *, build: bool = False) -> list[dict[str, Any]]:
    ns = namespace
    out: list[dict[str, Any]] = []
    try:
        registry = load_registry(root)
    except SketchUpAssetError as exc:
        return [_finding(ns, "registry", REGISTRY_REL, str(exc))]
    entry = registry.get(ns)
    if entry is None:
        out.append(_finding(ns, "registry", REGISTRY_REL, "namespace is not registered"))
    mpath = manifest_path(ns, root)
    mrel = _rel(mpath, root)
    if not mpath.exists():
        return [*out, _finding(ns, "manifest", mrel, "manifest.json is missing (run `manifest --write`)")]
    manifest_bytes = _check_text_file(ns, mpath, mrel, DEFAULT_LIMITS["max_input_bytes"], out)
    try:
        manifest = json.loads(manifest_bytes or b"")
    except ValueError as exc:
        return [*out, _finding(ns, "manifest", mrel, f"invalid JSON: {exc}")]
    errors = _schema_errors(manifest, root)
    out.extend(_finding(ns, "manifest-schema", mrel, e) for e in errors)
    if errors:
        return out
    if manifest["namespace"] != ns:
        out.append(_finding(ns, "manifest", mrel, f"namespace is {manifest['namespace']!r}"))
    limits = manifest["limits"]

    # ---- inputs: hashes, encoding, personal paths, size
    ns_dir = namespace_dir(ns, root)
    parsed: dict[str, tuple[str, Any]] = {}
    listed: set[str] = set()
    for item in manifest["inputs"]:
        rel = item["path"]
        listed.add(rel)
        path = root / rel
        data = _check_text_file(ns, path, rel, limits["max_input_bytes"], out)
        if data is None:
            continue
        if "sha256" in item and _sha256_bytes(data) != item["sha256"]:
            out.append(_finding(ns, "hash", rel, "sha256 does not match the manifest (capture changed?)"))
        if "bytes" in item and len(data) != item["bytes"]:
            out.append(_finding(ns, "hash", rel, f"{len(data)} bytes, manifest says {item['bytes']}"))
        if item["kind"] != "shared" and not path.resolve().is_relative_to(ns_dir.resolve()):
            out.append(_finding(ns, "manifest", rel, f"{item['kind']} input must live in {_rel(ns_dir, root)}"))
        if path.suffix == ".json":
            try:
                parsed[item["role"]] = (rel, json.loads(data.decode("utf-8")))
            except ValueError as exc:
                out.append(_finding(ns, "encoding", rel, f"invalid JSON: {exc}"))
    roles = {i["role"]: i for i in manifest["inputs"]}
    dump_item = roles.get("dump")
    if dump_item is None or dump_item["kind"] != "capture":
        out.append(_finding(ns, "manifest", mrel, "inputs need one capture with role 'dump'"))
    elif dump_item.get("sha256") != manifest["dump_sha256"]:
        out.append(_finding(ns, "hash", mrel, "dump_sha256 differs from the dump input"))
    for role, sha in manifest["probe_sha256"].items():
        if roles.get(role, {}).get("sha256") != sha:
            out.append(_finding(ns, "hash", mrel, f"probe_sha256[{role}] differs from the {role} input"))
    for role, item in roles.items():
        if role.endswith("_probe") and item["kind"] == "capture" and role not in manifest["probe_sha256"]:
            out.append(_finding(ns, "hash", mrel, f"probe_sha256 lacks {role}"))

    # ---- namespace folder: everything listed, no model binaries
    if ns_dir.exists():
        for f in sorted(p for p in ns_dir.rglob("*") if p.is_file()):
            rel = _rel(f, root)
            if f.suffix.lower() in BINARY_MODEL_SUFFIXES:
                out.append(_finding(ns, "skp-binary", rel, "SketchUp model binaries are never committed"))
            elif f.name != MANIFEST_NAME and rel not in listed:
                out.append(_finding(ns, "unlisted", rel, "file is not listed in manifest.json inputs"))
            elif f.suffix.lower() not in TEXT_SUFFIXES and f.name != MANIFEST_NAME:
                out.append(_finding(ns, "binary", rel, "only text captures (JSON/markdown) are committed"))
    else:
        out.append(_finding(ns, "missing", _rel(ns_dir, root), "namespace folder does not exist"))

    # ---- registry <-> manifest
    if entry is not None:
        for key, rel in entry.items():
            if key == "output":
                if rel not in {o["path"] for o in manifest["outputs"]}:
                    out.append(_finding(ns, "registry", rel, "registered output is not in manifest outputs"))
            elif rel not in listed:
                out.append(_finding(ns, "registry", rel, f"registered {key} is not in manifest inputs"))

    # ---- outputs
    for item in manifest["outputs"]:
        _check_text_file(ns, root / item["path"], item["path"], limits["max_output_bytes"], out)

    # ---- semantic checks on the captures and the overlay
    dump = parsed.get("dump", (None, None))[1]
    classes = None
    if "classes" in parsed:
        rel, vocab = parsed["classes"]
        if vocab.get("schema") != CLASSES_SCHEMA:
            out.append(_finding(ns, "classification", rel, f"schema must be {CLASSES_SCHEMA}"))
        classes = {c.get("id") for c in vocab.get("classes") or []}
    if "classification" in parsed:
        rel, data = parsed["classification"]
        out.extend(_check_classification(ns, rel, data, manifest["dump_sha256"], dump, classes))
    else:
        out.append(_finding(ns, "classification", mrel, "inputs need a classification.json overlay"))
    if "classification_supplement" in parsed:
        rel, data = parsed["classification_supplement"]
        if not str(data.get("schema", "")).startswith(SUPPLEMENT_SCHEMA_PREFIX):
            out.append(_finding(ns, "classification", rel, f"schema must start with {SUPPLEMENT_SCHEMA_PREFIX}"))
        for i, a in enumerate(data.get("assignments") or []):
            loc = f"{rel} $.assignments[{i}]"
            a = {"verification_state": None, "source_kind": None, **a}
            out.extend(_candidate_findings(ns, loc, a, locator=True))
    if isinstance(dump, dict):
        out.extend(_check_order(ns, dump, parsed))
    for rel, data in parsed.values():
        if _modified_state(data)[0] is False and _modified_state(data)[1] is True:
            out.append(_finding(ns, "model-modified", rel, "the read-only capture changed the model"))

    # ---- optional: regenerate and compare (same as `sketchup_assets build --check`)
    if build and entry is not None and not out:
        try:
            text = build_namespace(ns, root)
        except SketchUpAssetError as exc:
            out.append(_finding(ns, "build", entry["output"], f"build failed: {exc}"))
        else:
            target = root / entry["output"]
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                out.append(_finding(ns, "build", entry["output"], "committed export is stale (run `build`)"))
    return out


def preflight(namespace: str | None = None, root: Path = ROOT, *, build: bool = False) -> list[dict[str, Any]]:
    """All findings for one namespace, or for every registered namespace plus the shared source tree."""
    if namespace is not None:
        return preflight_namespace(namespace, root, build=build)
    out: list[dict[str, Any]] = []
    try:
        registry = load_registry(root)
    except SketchUpAssetError as exc:
        return [_finding(None, "registry", REGISTRY_REL, str(exc))]
    for ns in sorted(registry):
        out.extend(preflight_namespace(ns, root, build=build))
    src = root / SOURCES_REL
    if src.exists():
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            rel = _rel(f, root)
            ns_name = f.relative_to(src).parts[0] if len(f.relative_to(src).parts) > 1 else None
            if ns_name in registry:
                continue  # checked above
            if f.suffix.lower() in BINARY_MODEL_SUFFIXES:
                out.append(_finding(ns_name, "skp-binary", rel, "SketchUp model binaries are never committed"))
            elif f.name == "model_dump.json":
                out.append(_finding(ns_name, "registry", rel, "model dump folder is not a registered namespace"))
            elif f.suffix.lower() in TEXT_SUFFIXES:
                _check_text_file(ns_name, f, rel, DEFAULT_LIMITS["max_input_bytes"], out)
    return out


# --------------------------------------------------------------------------- scaffold

TEST_STUB = '''"""Regeneration test for the SketchUp namespace {ns!r}.

Emitted by `python -m sion_ingestion.sketchup_collection scaffold --namespace {ns}`; extend it with
spot facts (definition counts, a known placement, the SketchUp version) once the model is reviewed.
"""

from __future__ import annotations

import hashlib
import json

from sion_ingestion.sketchup_assets import DEFAULTS
from sion_ingestion.sketchup_collection import build_namespace, preflight

NAMESPACE = "{ns}"
DUMP_SHA256 = "{sha}"
PATHS = DEFAULTS[NAMESPACE]


def test_{ident}_dump_is_pinned():
    assert hashlib.sha256(PATHS["dump"].read_bytes()).hexdigest() == DUMP_SHA256
    overlay = json.loads(PATHS["classification"].read_text(encoding="utf-8"))
    assert overlay["model_dump_sha256"] == DUMP_SHA256


def test_{ident}_preflight_is_clean():
    assert preflight(NAMESPACE) == []


def test_{ident}_committed_export_matches_regeneration():
    assert PATHS["output"].read_text(encoding="utf-8") == build_namespace(NAMESPACE)
'''


def classification_skeleton(dump_sha: str) -> dict[str, Any]:
    return {
        "schema": CLASSIFICATION_SCHEMA,
        "model_dump": "model_dump.json",
        "model_dump_sha256": dump_sha,
        "method": "덤프와 프로브의 사실을 근거로 사람이 읽고 정한 분류. 모든 분류는 추론(source_kind=inferred, "
        "verification_state=unverified)이며 basis_ko에 근거 사실을 적는다. 자동 승인 없음(/review).",
        "assignments": [],
    }


def _repo_relative(value: str, flag: str) -> str:
    """Normalise a repo-relative override path; reject absolute paths and ``..`` components."""
    text = value.replace("\\", "/").strip()
    win = PureWindowsPath(value)
    posix = PurePosixPath(text)
    if not text or posix.is_absolute() or win.drive or win.root or ".." in posix.parts:
        raise CollectionError(f"{flag} {value!r} must be a repo-relative path without '..'")
    rel = posix.as_posix()
    if rel in ("", "."):
        raise CollectionError(f"{flag} {value!r} must name a file inside the repository")
    return rel


def _is_built(namespace: str, entry: dict[str, str], root: Path) -> bool:
    """A registered namespace counts as built once its manifest or its export exists."""
    return manifest_path(namespace, root).exists() or (root / entry["output"]).exists()


class _Journal:
    """Records every file scaffold writes so a failed run can be undone completely."""

    def __init__(self) -> None:
        self.files: list[tuple[Path, bytes | None]] = []
        self.dirs: list[Path] = []

    def write(self, path: Path, data: bytes) -> None:
        missing: list[Path] = []
        d = path.parent
        while not d.exists():
            missing.append(d)
            d = d.parent
        path.parent.mkdir(parents=True, exist_ok=True)
        self.dirs.extend(missing)
        self.files.append((path, path.read_bytes() if path.exists() else None))
        path.write_bytes(data)

    def rollback(self) -> None:
        for path, old in reversed(self.files):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(old)
        for d in sorted(set(self.dirs), key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass


def scaffold(
    namespace: str,
    root: Path = ROOT,
    *,
    from_dir: Path | None = None,
    guidelines: str | None = None,
    grouping_doc: str | None = None,
    classes: str | None = None,
    force: bool = False,
    write_test: bool = True,
) -> dict[str, Any]:
    """Register a namespace, write its manifest, build + check the export and emit a test stub.

    All inputs are validated and the export is built in memory before anything is written; if a
    later step fails, every file written by this call (registry included) is restored.
    """
    if not NAMESPACE_RE.match(namespace):
        raise CollectionError(f"namespace {namespace!r} must match {NAMESPACE_RE.pattern}")
    guidelines = _repo_relative(guidelines, "--guidelines") if guidelines is not None else None
    grouping_doc = _repo_relative(grouping_doc, "--grouping-doc") if grouping_doc is not None else None
    classes = _repo_relative(classes, "--classes") if classes is not None else None
    ns_dir = namespace_dir(namespace, root)
    actions: list[str] = []

    # 1) plan the capture copies from the SketchUp export folder (byte-for-byte); nothing written yet
    copies: dict[str, tuple[Path, bytes]] = {}
    if from_dir is not None:
        from_dir = Path(from_dir)
        if not from_dir.is_dir():
            raise CollectionError(f"--from-dir {from_dir} is not a directory")
        for src in sorted(from_dir.iterdir()):
            name = CAPTURE_RENAMES.get(src.name, src.name)
            if not src.is_file() or name not in KNOWN_FILES or KNOWN_FILES[name][1] != "capture":
                continue
            data = src.read_bytes()
            dst = ns_dir / name
            current = dst.read_bytes() if dst.exists() else None
            if current is not None and current != data and not force:
                raise CollectionError(f"{_rel(dst, root)} differs from {src.name}; pass --force to replace it")
            if current != data:
                copies[name] = (src, data)

    def has(name: str) -> bool:
        return name in copies or (ns_dir / name).exists()

    dump_path = ns_dir / "model_dump.json"
    if not has("model_dump.json"):
        raise CollectionError(f"{_rel(dump_path, root)} is missing (copy the dump_model.rb output first)")
    dump_bytes = copies["model_dump.json"][1] if "model_dump.json" in copies else dump_path.read_bytes()
    if dump_bytes.startswith(b"\xef\xbb\xbf"):
        raise CollectionError(f"{_rel(dump_path, root)} has a UTF-8 BOM; strip it before committing")
    dump_sha = _sha256_bytes(dump_bytes)

    # 2) proposed registry entry; shared inputs must already exist
    rel_dir = f"{SOURCES_REL}/{namespace}"
    entry = {
        "dump": f"{rel_dir}/model_dump.json",
        "classes": classes or SHARED_DEFAULTS["classes"],
        "classification": f"{rel_dir}/classification.json",
        "guidelines": guidelines or SHARED_DEFAULTS["guidelines"],
        "output": f"data/bootstrap/sketchup-{namespace}.json",
    }
    if has("geometry_probe.json"):
        entry["probe"] = f"{rel_dir}/geometry_probe.json"
    if has("grouping_probe.json"):
        entry["grouping_probe"] = f"{rel_dir}/grouping_probe.json"
        if grouping_doc:
            entry["grouping_doc"] = grouping_doc
    elif grouping_doc:
        raise CollectionError("--grouping-doc needs grouping_probe.json in the namespace folder")
    for key in ("classes", "guidelines", "grouping_doc"):
        if key in entry and not (root / entry[key]).is_file():
            raise CollectionError(f"{key} input {entry[key]} does not exist")
    registry = load_registry(root)
    existing = registry.get(namespace)
    if existing not in (None, entry) and not force and _is_built(namespace, existing, root):
        raise CollectionError(f"namespace {namespace!r} is already registered differently; pass --force")

    journal = _Journal()
    try:
        # 3) captures and the classification overlay skeleton (pinned to the dump, nothing approved)
        for name, (src, data) in copies.items():
            journal.write(ns_dir / name, data)
            actions.append(f"copied {src.name} -> {_rel(ns_dir / name, root)}")
        cls_path = ns_dir / "classification.json"
        if not cls_path.exists():
            journal.write(cls_path, _json_text(classification_skeleton(dump_sha)).encode("utf-8"))
            actions.append(f"wrote {_rel(cls_path, root)} (empty, pinned to the dump)")

        # 4) build from the proposed entry, then build --check (an independent rebuild must match)
        try:
            text = _build_entry(namespace, entry, root)
            if text != _build_entry(namespace, entry, root):
                raise CollectionError("build --check failed: the export is not deterministic")
        except SketchUpAssetError as exc:
            raise CollectionError(
                f"build failed: {exc}. Guideline/grouping documents cite model-specific evidence "
                "(def:, obj:, occ:); pass --guidelines/--grouping-doc written for this model."
            ) from exc

        # 5) only now register the namespace and write the export
        if existing != entry:
            registry[namespace] = entry
            journal.write(root / REGISTRY_REL, registry_text(registry).encode("utf-8"))
            actions.append(f"registered {namespace} in {REGISTRY_REL}")
        out_path = root / entry["output"]
        if not out_path.exists() or out_path.read_text(encoding="utf-8") != text:
            journal.write(out_path, text.encode("utf-8"))
        actions.append(f"built {entry['output']}")
        actions.append("build --check: up to date")

        # 6) manifest
        mpath = manifest_path(namespace, root)
        journal.write(mpath, manifest_text(namespace, root).encode("utf-8"))
        actions.append(f"wrote {_rel(mpath, root)}")

        # 7) regeneration test stub
        ident = re.sub(r"[^0-9a-z]+", "_", namespace).strip("_")
        test_path = root / "tests" / f"test_sketchup_ns_{ident}.py"
        if write_test and not test_path.exists():
            stub = TEST_STUB.format(ns=namespace, sha=dump_sha, ident=ident)
            journal.write(test_path, stub.encode("utf-8"))
            actions.append(f"wrote {_rel(test_path, root)}")
    except BaseException:
        journal.rollback()
        raise

    findings = preflight_namespace(namespace, root)
    return {"namespace": namespace, "actions": actions, "preflight": findings, "ok": not findings}


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sion_ingestion.sketchup_collection", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight", help="validate manifests, captures, overlays and outputs (read-only)")
    p.add_argument("--namespace")
    p.add_argument("--build", action="store_true", help="also regenerate the export and compare (build --check)")
    p = sub.add_parser("manifest", help="print, write or check a namespace manifest")
    p.add_argument("--namespace", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    p = sub.add_parser("scaffold", help="register a namespace, build + check it, write manifest and test stub")
    p.add_argument("--namespace", required=True)
    p.add_argument("--from-dir", help="SketchUp export folder with model_dump.json / geom_probe.json / ...")
    p.add_argument("--guidelines", help=f"repo-relative guideline markdown (default {SHARED_DEFAULTS['guidelines']})")
    p.add_argument("--grouping-doc", help="repo-relative grouping workflow markdown written for this model")
    p.add_argument("--classes", help=f"repo-relative class vocabulary (default {SHARED_DEFAULTS['classes']})")
    p.add_argument("--force", action="store_true", help="replace differing captures / an already built registry entry")
    p.add_argument("--no-test", action="store_true", help="do not emit tests/test_sketchup_ns_<ns>.py")
    args = parser.parse_args(argv)

    try:
        if args.command == "preflight":
            findings = preflight(args.namespace, build=args.build)
            namespaces = [args.namespace] if args.namespace else sorted(load_registry(ROOT))
            warnings = [w for ns in namespaces for w in preflight_warnings(ns)]
            report = {"ok": not findings, "findings": findings, "warnings": warnings}
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 0 if not findings else 1
        if args.command == "manifest":
            text = manifest_text(args.namespace)
            path = manifest_path(args.namespace)
            if args.check:
                same = path.exists() and path.read_bytes() == text.encode("utf-8")
                print(json.dumps({"namespace": args.namespace, "up_to_date": same}))
                return 0 if same else 1
            if args.write:
                path.write_bytes(text.encode("utf-8"))  # LF on every OS
                print(json.dumps({"written": _rel(path, ROOT)}, ensure_ascii=False))
            else:
                sys.stdout.write(text)
            return 0
        result = scaffold(
            args.namespace,
            from_dir=Path(args.from_dir) if args.from_dir else None,
            guidelines=args.guidelines,
            grouping_doc=args.grouping_doc,
            classes=args.classes,
            force=args.force,
            write_test=not args.no_test,
        )
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["ok"] else 1
    except CollectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
