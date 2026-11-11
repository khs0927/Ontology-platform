"""SketchUp model collection pipeline: one ingest command, manifest and preflight.

Every collected SketchUp model lives in one *namespace*:

* ``data/sources/sketchup/<namespace>/`` holds the read-only captures (``model_dump.json``,
  ``geometry_probe.json``, ``grouping_probe.json``, ``hierarchy.json``, ...) and the authored
  overlays (``classification.json``, pinned to the dump SHA-256),
* ``data/sources/sketchup/<namespace>/manifest.json`` (``sion-sketchup-collection-manifest/v1``,
  JSON schema ``schemas/sion-sketchup-collection-manifest-1.schema.json``) records the model,
  SketchUp version, capture hashes, inputs and outputs,
* ``data/sources/sketchup/content-index.json`` (``sion-sketchup-content-index/v1``) maps the
  committed dump SHA-256 (the content address) to exactly one namespace,
* ``data/sources/sketchup/namespaces.json`` (``sion-sketchup-namespaces/v1``) registers the build
  inputs for :mod:`sion_ingestion.sketchup_assets`.

Commands::

    python -m sion_ingestion.sketchup_collection ingest --namespace NS --from-dir DIR [...]
    python -m sion_ingestion.sketchup_collection preflight [--namespace NS] [--build]
    python -m sion_ingestion.sketchup_collection manifest --namespace NS [--write | --check]
    python -m sion_ingestion.sketchup_collection scaffold --namespace NS [--from-dir DIR] [...]

``ingest`` is the command that adds a model. It strips a UTF-8 BOM, redacts personal absolute
paths, content-addresses the committed dump, and writes classification candidates only when a
definition attribute (``sion_class``, ``object_class`` or ``su_class``) is exactly a known class
id. Those candidates stay ``unverified`` for ``/review``, with the dump locator and SHA-256.
Re-running it on the same bytes changes nothing. The same dump cannot be registered twice.

The preflight never modifies anything. ``scaffold`` is the writer ``ingest`` calls: captures, the
classification overlay, the registry entry, the manifest, the content index, the generated export
and a regeneration test stub. If a later step fails, every file written by that call is restored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
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
CONTENT_INDEX_SCHEMA = "sion-sketchup-content-index/v1"
CONTENT_INDEX_REL = "data/sources/sketchup/content-index.json"
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
#: Attribute keys whose string value is copied as a class id. Anything else is not a classification.
EXPLICIT_CLASS_KEYS = frozenset({"sion_class", "object_class", "su_class"})
#: Declared constant for "the attribute names a vocabulary id". It is not a measured probability.
EXPLICIT_CLASS_CONFIDENCE = 0.55
EXPLICIT_METHOD = (
    "명시적 속성(sion_class, object_class, su_class)의 값이 객체 클래스 id와 정확히 같을 때만 "
    "미검증 후보를 만든다. 이름·크기·재질로 클래스를 추정하지 않는다. "
    f"confidence는 파이프라인 상수 {EXPLICIT_CLASS_CONFIDENCE}이다. "
    "verification_state=unverified, source_kind=inferred. 근거 locator와 SHA-256을 보존하며 "
    "/review 승인 전에는 GraphRAG 가중치에 반영하지 않는다."
)
READONLY_SCRIPTS = (
    "scripts/sketchup/dump_model.rb",
    "scripts/sketchup/geom_probe.rb",
    "scripts/sketchup/grouping_probe.rb",
)
#: A dotted call that would change the open model. Comments that merely say "save" do not match.
MUTATION_RE = re.compile(rb"\.(?:save|erase!|add_face|add_group|add_instance|pushpull|start_operation)\b|purge_unused")
_ATTR_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LOCATOR_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")

# Personal absolute paths. Generic profile names (as in scripts/check_public_privacy.py) are allowed.
WIN_PROFILE_RE = re.compile(rb"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+([^\\/\s\"'`\r\n]+)", re.IGNORECASE)
NIX_PROFILE_RE = re.compile(rb"(?<![\w.~:-])/(?:home|Users)/([^/\s\"'`\\\r\n]+)")
_WIN_PATH_RE = re.compile(
    rb"[A-Za-z]:(?:\\\\|/|\\)(?:Users|Documents and Settings)(?:\\\\|/|\\)"
    rb"([^\\/\s\"'`\r\n]+)"
    rb"((?:(?:\\\\|/|\\)[^\\/\s\"'`\r\n]+)*)",
    re.IGNORECASE,
)
_NIX_PATH_RE = re.compile(rb"(?<![\w.~:-])/(?:home|Users)/([^/\s\"'`\\\r\n]+)((?:/[^/\s\"'`\\\r\n]+)*)")
_PATH_SPLIT_RE = re.compile(rb"(?:\\\\|/|\\)")
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


def _path_basename(rest: bytes) -> bytes:
    parts = [part for part in _PATH_SPLIT_RE.split(rest or b"") if part]
    return parts[-1] if parts else b""


def redact_personal_paths(data: bytes) -> tuple[bytes, int]:
    """Replace personal absolute paths with ``<redacted>/<filename>``. Generic profiles stay.

    The replacement keeps the final path segment so ``model.path`` still yields the ``.skp``
    file name. Generic profile names (``USER``, ``user``, …) are left as written.
    """
    count = 0

    def repl(match: re.Match[bytes]) -> bytes:
        nonlocal count
        if _is_generic_profile(match.group(1)):
            return match.group(0)
        count += 1
        tail = _path_basename(match.group(2) or b"")
        return b"<redacted>/" + tail if tail else b"<redacted>"

    redacted = _WIN_PATH_RE.sub(repl, data)
    redacted = _NIX_PATH_RE.sub(repl, redacted)
    return redacted, count


def prepare_capture_bytes(data: bytes) -> tuple[bytes, int]:
    """Strip one leading UTF-8 BOM, then redact personal paths. The result is what we commit."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return redact_personal_paths(data)


def capture_set_sha256(items: list[tuple[str, str, str]]) -> str:
    """Content address of a capture set: role, repo-relative path and SHA-256, sorted."""
    digest = hashlib.sha256()
    for role, path, sha in sorted(items):
        digest.update(role.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
    return digest.hexdigest()


def resolve_locator(document: Any, locator: str) -> Any:
    """Resolve a ``$.a[0].b`` locator. Return ``None`` when a step is missing."""
    if not isinstance(locator, str) or not locator.startswith("$"):
        return None
    current = document
    for key, index in _LOCATOR_RE.findall(locator):
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        else:
            i = int(index)
            if not isinstance(current, list) or i >= len(current) or i < 0:
                return None
            current = current[i]
    return current


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
    capture_items = [(i["role"], i["path"], i["sha256"]) for i in inputs if i["kind"] == "capture" and "sha256" in i]
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
        "content_address": dump_item["sha256"],
        "capture_set_sha256": capture_set_sha256(capture_items),
        "probe_sha256": {i["role"]: i["sha256"] for i in inputs if i["role"].endswith("_probe") and "sha256" in i},
        "limits": limits,
        "inputs": inputs,
        "outputs": outputs,
    }


def manifest_text(namespace: str, root: Path = ROOT) -> str:
    return _json_text(build_manifest(namespace, root))


def build_content_index(root: Path = ROOT) -> dict[str, Any]:
    """One entry per committed dump SHA-256. Two namespaces cannot share a model snapshot."""
    by_dump: dict[str, dict[str, str]] = {}
    for namespace in sorted(load_registry(root)):
        manifest = build_manifest(namespace, root)
        sha = manifest["content_address"]
        if sha in by_dump:
            raise CollectionError(
                f"dump {sha} is already ingested as namespace {by_dump[sha]['namespace']!r}; "
                f"{namespace!r} would be a second copy"
            )
        by_dump[sha] = {
            "namespace": namespace,
            "capture_set_sha256": manifest["capture_set_sha256"],
            "skp_file": manifest["model"]["skp_file"],
        }
    return {
        "schema": CONTENT_INDEX_SCHEMA,
        "description": "Content address (SHA-256 of the committed model_dump.json, after BOM strip and "
        "personal-path redaction) -> the one namespace that ingested it. "
        "Edit with `python -m sion_ingestion.sketchup_collection ingest`.",
        "by_dump_sha256": by_dump,
    }


def content_index_text(root: Path = ROOT) -> str:
    return _json_text(build_content_index(root))


def content_index_owner(root: Path, dump_sha: str) -> str | None:
    """Namespace that already committed this dump SHA-256, or ``None`` when the index has no such entry."""
    path = root / CONTENT_INDEX_REL
    if not path.exists():
        return None
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CollectionError(f"{CONTENT_INDEX_REL} is not valid JSON: {exc}") from exc
    if index.get("schema") != CONTENT_INDEX_SCHEMA or not isinstance(index.get("by_dump_sha256"), dict):
        raise CollectionError(f"{CONTENT_INDEX_REL} is not a {CONTENT_INDEX_SCHEMA} document")
    entry = index["by_dump_sha256"].get(dump_sha)
    if entry is None:
        return None
    owner = entry.get("namespace")
    if not isinstance(owner, str):
        raise CollectionError(f"{CONTENT_INDEX_REL} entry for {dump_sha} has no namespace")
    return owner


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
        evidence_sha = a.get("evidence_sha256")
        if evidence_sha is not None and evidence_sha != dump_sha:
            out.append(_finding(ns, "classification", loc, "evidence_sha256 does not match the model dump"))
        locator = a.get("evidence_locator")
        if locator is not None:
            if not isinstance(locator, str) or not locator.startswith("$."):
                out.append(_finding(ns, "classification", loc, "evidence_locator must be a $. locator"))
            elif isinstance(dump, dict) and resolve_locator(dump, locator) != a.get("class"):
                out.append(
                    _finding(ns, "classification", loc, "evidence_locator does not resolve to the class id")
                )
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
        # geom_probe.json is a name -> geometry map plus a "_meta" block (modified_before/after)
        unknown = sorted(k for k in probe if not str(k).startswith("_") and k not in dump_defs) if isinstance(probe, dict) else []
        if unknown:
            out.append(_finding(ns, "hierarchy-order", rel, f"{len(unknown)} probed definition(s) not in the dump"))
    return out


def _check_explicit_coverage(
    ns: str, dump: dict[str, Any], classification: dict[str, Any], class_ids: set[str], dump_sha: str
) -> list[dict[str, Any]]:
    """Every explicit class attribute must still be an unverified candidate with its locator."""
    try:
        proposed = propose_explicit_classifications(dump, class_ids, dump_sha)
    except CollectionError as exc:
        return [_finding(ns, "classification", "model_dump.json", str(exc))]
    by_definition = {a.get("definition"): a for a in classification.get("assignments") or []}
    out: list[dict[str, Any]] = []
    for item in proposed:
        got = by_definition.get(item["definition"])
        loc = f"$.definitions {item['definition']}"
        if not isinstance(got, dict) or got.get("class") != item["class"]:
            out.append(
                _finding(ns, "classification", loc, "explicit class attribute has no matching unverified candidate")
            )
            continue
        if got.get("evidence_locator") != item["evidence_locator"] or got.get("evidence_sha256") != dump_sha:
            out.append(
                _finding(ns, "classification", loc, "candidate dropped the attribute locator or dump SHA-256")
            )
    return out


def _check_model_unchanged(
    ns: str, dump: dict[str, Any], parsed: dict[str, tuple[str, Any]], manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    """The read-only captures must agree on ``model.modified?`` and must not have flipped it."""
    out: list[dict[str, Any]] = []
    modified = (dump.get("model") or {}).get("modified")
    recorded = (manifest.get("model") or {}).get("modified")
    if recorded != modified:
        out.append(
            _finding(ns, "model-unchanged", "manifest.json", f"manifest model.modified is {recorded!r}; the dump says {modified!r}")
        )
    if "grouping_probe" in parsed:
        rel, probe = parsed["grouping_probe"]
        if "model_modified" in probe and probe.get("model_modified") != modified:
            out.append(
                _finding(ns, "model-unchanged", rel, "grouping probe model_modified disagrees with the model dump")
            )
        if probe.get("active_path"):
            out.append(
                _finding(ns, "model-unchanged", rel, "grouping probe ran inside an active edit path, not the model root")
            )
    if "hierarchy" in parsed:
        rel, hierarchy = parsed["hierarchy"]
        before, after = hierarchy.get("modified_before"), hierarchy.get("modified_after")
        if before is not None and after is not None and before != after:
            out.append(
                _finding(ns, "model-unchanged", rel, "export_objects changed model.modified while it was running")
            )
        if before is not None and modified is not None and before != modified:
            out.append(
                _finding(ns, "model-unchanged", rel, "hierarchy modified_before disagrees with the model dump")
            )
    return out


def _check_content_address(ns: str, root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The dump SHA-256 is the content address, and the content index names this namespace only."""
    out: list[dict[str, Any]] = []
    dump_sha = manifest.get("dump_sha256")
    if manifest.get("content_address") != dump_sha:
        out.append(_finding(ns, "content-address", "manifest.json", "content_address must be the committed dump SHA-256"))
    live: list[tuple[str, str, str]] = []
    for item in manifest["inputs"]:
        if item.get("kind") != "capture":
            continue
        path = root / item["path"]
        if not path.is_file():
            continue
        live.append((item["role"], item["path"], _sha256_bytes(path.read_bytes())))
    if live and capture_set_sha256(live) != manifest.get("capture_set_sha256"):
        out.append(_finding(ns, "content-address", "manifest.json", "capture_set_sha256 does not match the capture bytes"))
    index_path = root / CONTENT_INDEX_REL
    if not index_path.is_file():
        return [*out, _finding(ns, "content-address", CONTENT_INDEX_REL, "content index is missing")]
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [*out, _finding(ns, "content-address", CONTENT_INDEX_REL, f"invalid JSON: {exc}")]
    if index.get("schema") != CONTENT_INDEX_SCHEMA or not isinstance(index.get("by_dump_sha256"), dict):
        return [*out, _finding(ns, "content-address", CONTENT_INDEX_REL, f"schema must be {CONTENT_INDEX_SCHEMA}")]
    by_dump = index["by_dump_sha256"]
    entry = by_dump.get(dump_sha)
    if not isinstance(entry, dict) or entry.get("namespace") != ns:
        owner = entry.get("namespace") if isinstance(entry, dict) else None
        message = (
            f"dump is already ingested as namespace {owner!r}"
            if owner
            else "dump SHA-256 is not the content-index entry for this namespace"
        )
        out.append(_finding(ns, "content-address", CONTENT_INDEX_REL, message))
    elif entry.get("capture_set_sha256") != manifest.get("capture_set_sha256"):
        out.append(_finding(ns, "content-address", CONTENT_INDEX_REL, "content index capture set is stale"))
    owners = [sha for sha, item in by_dump.items() if isinstance(item, dict) and item.get("namespace") == ns]
    if owners != [dump_sha]:
        out.append(_finding(ns, "content-address", CONTENT_INDEX_REL, "namespace must have exactly one content address"))
    return out


def _readonly_script_findings(root: Path) -> list[dict[str, Any]]:
    """The capture scripts that ingest tells the operator to run must not mutate the model."""
    out: list[dict[str, Any]] = []
    for rel in READONLY_SCRIPTS:
        path = root / rel
        if not path.is_file():
            continue
        if MUTATION_RE.search(path.read_bytes()):
            out.append(
                _finding(None, "model-unchanged", rel, "read-only capture script contains a model mutation")
            )
    return out


def _modified_state(data: Any) -> tuple[Any, Any]:
    """(modified_before, modified_after) of a capture, top level, under ``model`` or under ``_meta``.

    The probes put the pair at the top level (``grouping_probe.json``, ``hierarchy.json``), under
    ``model`` (``model_dump.json``) or in the ``_meta`` block (``geometry_probe.json``); None when absent.
    """
    if not isinstance(data, dict):
        return None, None
    for d in (data, data.get("model"), data.get("_meta")):
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
        if isinstance(dump, dict):
            out.extend(_check_explicit_coverage(ns, dump, data, classes or set(), manifest["dump_sha256"]))
    else:
        out.append(_finding(ns, "classification", mrel, "inputs need a classification.json overlay"))
    if "classification_supplement" in parsed:
        rel, data = parsed["classification_supplement"]
        if not str(data.get("schema", "")).startswith(SUPPLEMENT_SCHEMA_PREFIX):
            out.append(_finding(ns, "classification", rel, f"schema must start with {SUPPLEMENT_SCHEMA_PREFIX}"))
        hierarchy_doc = parsed.get("hierarchy", (None, None))[1]
        for i, a in enumerate(data.get("assignments") or []):
            loc = f"{rel} $.assignments[{i}]"
            a = {"verification_state": None, "source_kind": None, **a}
            out.extend(_candidate_findings(ns, loc, a, locator=True))
            pointer = a.get(LOCATOR_KEY)
            if isinstance(pointer, str) and pointer.strip() and not pointer.startswith("$."):
                out.append(_finding(ns, "candidate", loc, "hierarchy_locator must stay on the supplement candidate"))
            elif isinstance(pointer, str) and pointer.startswith("$.") and isinstance(hierarchy_doc, dict):
                node = resolve_locator(hierarchy_doc, pointer)
                if not isinstance(node, dict) or node.get("pid") != a.get("pid"):
                    out.append(
                        _finding(ns, "candidate", loc, "hierarchy_locator does not resolve to this assignment's pid")
                    )
    if isinstance(dump, dict):
        out.extend(_check_order(ns, dump, parsed))
        out.extend(_check_model_unchanged(ns, dump, parsed, manifest))
        out.extend(_check_content_address(ns, root, manifest))
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
    out.extend(_readonly_script_findings(root))
    return out


# --------------------------------------------------------------------------- scaffold

TEST_STUB = '''"""Regeneration test for the SketchUp namespace {ns!r}.

Emitted by `python -m sion_ingestion.sketchup_collection ingest --namespace {ns}`; extend it with
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

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: list[tuple[Path, bytes | None]] = []
        self.dirs: list[Path] = []

    def write(self, path: Path, data: bytes) -> None:
        if not path.is_relative_to(self.root) or path.resolve() != path:
            raise CollectionError("scaffold output must be a direct path inside the repository")
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
    classification_document: dict[str, Any] | None = None,
    force: bool = False,
    write_test: bool = True,
) -> dict[str, Any]:
    """Register a namespace, write its manifest, build + check the export and emit a test stub.

    If the build or final preflight fails, every file written by this call
    (including the registry) is restored.
    """
    if not NAMESPACE_RE.match(namespace):
        raise CollectionError(f"namespace {namespace!r} must match {NAMESPACE_RE.pattern}")
    root = root.resolve()
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
    owner = content_index_owner(root, dump_sha)
    if owner not in (None, namespace):
        raise CollectionError(
            f"this model dump is already ingested as namespace {owner!r} (content address {dump_sha}). "
            "Re-run ingest on that namespace; the same snapshot is not copied twice."
        )
    cls_path = ns_dir / "classification.json"
    cls_bytes: bytes | None = None
    if classification_document is not None:
        if classification_document.get("schema") != CLASSIFICATION_SCHEMA:
            raise CollectionError(f"classification schema must be {CLASSIFICATION_SCHEMA}")
        if classification_document.get("model_dump_sha256") != dump_sha:
            raise CollectionError("classification model_dump_sha256 is not this dump's content address")
        cls_bytes = _json_text(classification_document).encode("utf-8")
        if cls_path.exists() and cls_path.read_bytes() != cls_bytes and not force:
            raise CollectionError(f"{_rel(cls_path, root)} differs from the ingested classification; pass --force")

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

    journal = _Journal(root)
    try:
        # 3) captures and the classification overlay skeleton (pinned to the dump, nothing approved)
        for name, (src, data) in copies.items():
            journal.write(ns_dir / name, data)
            actions.append(f"copied {src.name} -> {_rel(ns_dir / name, root)}")
        if cls_bytes is not None:
            if not cls_path.exists() or cls_path.read_bytes() != cls_bytes:
                journal.write(cls_path, cls_bytes)
                actions.append(f"wrote {_rel(cls_path, root)} (unverified candidates, pinned to the dump)")
        elif not cls_path.exists():
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

        # 7) content index (dump SHA-256 -> this namespace) and the regeneration test stub
        index_bytes = content_index_text(root).encode("utf-8")
        index_path = root / CONTENT_INDEX_REL
        if not index_path.exists() or index_path.read_bytes() != index_bytes:
            journal.write(index_path, index_bytes)
            actions.append(f"wrote {CONTENT_INDEX_REL}")
        ident = re.sub(r"[^0-9a-z]+", "_", namespace).strip("_")
        test_path = root / "tests" / f"test_sketchup_ns_{ident}.py"
        if write_test and not test_path.exists():
            stub = TEST_STUB.format(ns=namespace, sha=dump_sha, ident=ident)
            journal.write(test_path, stub.encode("utf-8"))
            actions.append(f"wrote {_rel(test_path, root)}")

        findings = preflight_namespace(namespace, root)
    except BaseException:
        journal.rollback()
        raise

    if findings:
        journal.rollback()
        return {"namespace": namespace, "actions": [], "preflight": findings, "ok": False}
    return {"namespace": namespace, "actions": actions, "preflight": [], "ok": True}


# --------------------------------------------------------------------------- ingest


def _explicit_labels(attributes: Any, prefix: str) -> list[tuple[str, str]]:
    """``(locator, value)`` for explicit class attributes. Nested dictionaries are walked.

    A value under any other key is ignored. This does not guess a class from a name, tag,
    material or size.
    """
    found: list[tuple[str, str]] = []
    if not isinstance(attributes, dict):
        return found
    for key, value in attributes.items():
        if not isinstance(key, str) or _ATTR_KEY_RE.fullmatch(key) is None:
            if key in EXPLICIT_CLASS_KEYS and isinstance(value, str):
                raise CollectionError(
                    f"{prefix}: attribute name {key!r} cannot be used as a locator. No class was guessed."
                )
            continue
        locator = f"{prefix}.{key}"
        if key in EXPLICIT_CLASS_KEYS and isinstance(value, str):
            found.append((locator, value))
        elif isinstance(value, dict):
            found.extend(_explicit_labels(value, locator))
    return found


def propose_explicit_classifications(
    dump: dict[str, Any], class_ids: set[str], dump_sha: str
) -> list[dict[str, Any]]:
    """Unverified candidates copied from explicit class attributes. Unknown ids are an error.

    Nothing is invented when a definition has no such attribute. Conflicting attributes on one
    definition are an error: the pipeline does not pick one.
    """
    assignments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, definition in enumerate(dump.get("definitions") or []):
        name = definition.get("name")
        if not isinstance(name, str) or not name:
            raise CollectionError(f"$.definitions[{index}] has no name")
        if name in seen:
            raise CollectionError(f"definition {name!r} appears more than once. No class was guessed.")
        seen.add(name)
        labels = _explicit_labels(definition.get("attributes") or {}, f"$.definitions[{index}].attributes")
        if not labels:
            continue
        classes = {value for _, value in labels}
        if len(classes) != 1:
            quoted = ", ".join(f"{loc}={value!r}" for loc, value in labels)
            raise CollectionError(
                f"definition {name!r} has conflicting class attributes ({quoted}). No class was chosen."
            )
        value = labels[0][1]
        if value not in class_ids:
            raise CollectionError(
                f"{labels[0][0]} is {value!r}, which is not an object-class id. No class was guessed."
            )
        locator = labels[0][0]
        assignments.append(
            {
                "definition": name,
                "class": value,
                "confidence": EXPLICIT_CLASS_CONFIDENCE,
                "verification_state": "unverified",
                "source_kind": "inferred",
                "basis_ko": (
                    f"덤프 속성 {locator} 의 값이 클래스 id '{value}'와 같다. "
                    f"파이프라인 상수 confidence={EXPLICIT_CLASS_CONFIDENCE}. 자동 승인 없음(/review)."
                ),
                "evidence_locator": locator,
                "evidence_sha256": dump_sha,
            }
        )
    return assignments


def build_classification_document(
    dump: dict[str, Any],
    class_ids: set[str],
    dump_sha: str,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pin ``existing`` (or a new document) to ``dump_sha`` and fill gaps from explicit attributes.

    An authored assignment is kept. An explicit attribute that names a different class is an error.
    """
    proposed = propose_explicit_classifications(dump, class_ids, dump_sha)
    if existing is None:
        document = classification_skeleton(dump_sha)
        document["method"] = EXPLICIT_METHOD
        document["assignments"] = proposed
        return document
    document = json.loads(json.dumps(existing))
    document["schema"] = CLASSIFICATION_SCHEMA
    document["model_dump"] = document.get("model_dump") or "model_dump.json"
    document["model_dump_sha256"] = dump_sha
    assignments = list(document.get("assignments") or [])
    by_definition: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        name = assignment.get("definition")
        if name in by_definition:
            raise CollectionError(f"classification lists definition {name!r} twice")
        if isinstance(name, str):
            by_definition[name] = assignment
    for item in proposed:
        previous = by_definition.get(item["definition"])
        if previous is None:
            assignments.append(item)
        elif previous.get("class") != item["class"]:
            raise CollectionError(
                f"{item['definition']!r}: attribute class {item['class']!r} disagrees with authored class "
                f"{previous.get('class')!r}. No class was chosen."
            )
        else:
            if previous.get("evidence_locator") not in (None, item["evidence_locator"]):
                raise CollectionError(
                    f"{item['definition']!r}: evidence_locator does not point at the class attribute"
                )
            if not previous.get("evidence_locator"):
                previous["evidence_locator"] = item["evidence_locator"]
            if previous.get("evidence_sha256") not in (None, dump_sha):
                raise CollectionError(f"{item['definition']!r}: evidence_sha256 is not this dump")
            if not previous.get("evidence_sha256"):
                previous["evidence_sha256"] = dump_sha
    document["assignments"] = assignments
    return document


def _load_class_ids(root: Path, classes: str | None) -> set[str]:
    rel = _repo_relative(classes, "--classes") if classes is not None else SHARED_DEFAULTS["classes"]
    path = root / rel
    if not path.is_file():
        raise CollectionError(f"classes input {rel} does not exist")
    vocab = json.loads(path.read_text(encoding="utf-8"))
    if vocab.get("schema") != CLASSES_SCHEMA:
        raise CollectionError(f"{rel}: expected schema {CLASSES_SCHEMA}")
    return {c["id"] for c in vocab.get("classes") or [] if isinstance(c, dict) and c.get("id")}


def _stage_captures(from_dir: Path) -> tuple[Path, int, dict[str, Any] | None, tempfile.TemporaryDirectory[str]]:
    """Copy redacted JSON captures into a temporary export folder. ``.skp`` and renders are skipped."""
    if not from_dir.is_dir():
        raise CollectionError(f"--from-dir {from_dir} is not a directory")
    temp = tempfile.TemporaryDirectory(prefix="su-ingest-")
    staged = Path(temp.name)
    redacted = 0
    authored: dict[str, Any] | None = None
    for src in sorted(from_dir.iterdir()):
        if not src.is_file():
            continue
        if src.suffix.lower() in BINARY_MODEL_SUFFIXES:
            continue
        name = CAPTURE_RENAMES.get(src.name, src.name)
        if name == "classification.json":
            data, count = prepare_capture_bytes(src.read_bytes())
            redacted += count
            if personal_paths(data):
                temp.cleanup()
                raise CollectionError(f"{src.name} still contains a personal absolute path after redaction")
            try:
                authored = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                temp.cleanup()
                raise CollectionError(f"{src.name} is not UTF-8 JSON after redaction: {exc}") from exc
            continue
        if name not in KNOWN_FILES or KNOWN_FILES[name][1] != "capture":
            continue
        data, count = prepare_capture_bytes(src.read_bytes())
        redacted += count
        if personal_paths(data):
            temp.cleanup()
            raise CollectionError(f"{src.name} still contains a personal absolute path after redaction")
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            temp.cleanup()
            raise CollectionError(f"{src.name} is not UTF-8 JSON after redaction: {exc}") from exc
        (staged / src.name).write_bytes(data)
    if not (staged / "model_dump.json").is_file():
        temp.cleanup()
        raise CollectionError(f"{from_dir} has no model_dump.json (refusing to invent a model)")
    return staged, redacted, authored, temp


def _parsed_capture(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def ingest(
    namespace: str,
    root: Path = ROOT,
    *,
    from_dir: Path,
    guidelines: str | None = None,
    grouping_doc: str | None = None,
    classes: str | None = None,
    force: bool = False,
    write_test: bool = True,
) -> dict[str, Any]:
    """Add one SketchUp model. Idempotent for the same redacted bytes; content-addressed by dump SHA-256.

    Personal paths are removed before anything is committed. Classification candidates are copied
    from explicit class attributes only and stay unverified. ``.skp`` binaries are not copied.
    """
    root = Path(root).resolve()
    staged, redacted, authored, temp = _stage_captures(Path(from_dir))
    try:
        dump = json.loads((staged / "model_dump.json").read_text(encoding="utf-8"))
        if not isinstance(dump, dict):
            raise CollectionError("model_dump.json must be a JSON object")
        parsed: dict[str, tuple[str, Any]] = {"dump": ("model_dump.json", dump)}
        grouping = _parsed_capture(staged / "grouping_probe.json")
        if grouping is not None:
            parsed["grouping_probe"] = ("grouping_probe.json", grouping)
        hierarchy = _parsed_capture(staged / "hierarchy.json")
        if hierarchy is not None:
            parsed["hierarchy"] = ("hierarchy.json", hierarchy)
        geometry_name = "geom_probe.json" if (staged / "geom_probe.json").is_file() else "geometry_probe.json"
        geometry = _parsed_capture(staged / geometry_name)
        if geometry is not None:
            parsed["geometry_probe"] = (geometry_name, geometry)
        findings = _check_order(namespace, dump, parsed) if isinstance(dump.get("hierarchy"), list) else [
            _finding(namespace, "hierarchy-order", "model_dump.json", "model dump has no hierarchy list")
        ]
        manifest_view = {"model": {"modified": (dump.get("model") or {}).get("modified")}}
        findings.extend(_check_model_unchanged(namespace, dump, parsed, manifest_view))
        if findings:
            messages = "; ".join(f["message"] for f in findings)
            raise CollectionError(f"read-only capture check failed: {messages}")
        dump_sha = _sha256_bytes((staged / "model_dump.json").read_bytes())
        class_ids = _load_class_ids(root, classes)
        existing_path = namespace_dir(namespace, root) / "classification.json"
        if existing_path.is_file():
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        else:
            existing = authored if isinstance(authored, dict) else None
        document = build_classification_document(dump, class_ids, dump_sha, existing)
        result = scaffold(
            namespace,
            root,
            from_dir=staged,
            guidelines=guidelines,
            grouping_doc=grouping_doc,
            classes=classes,
            classification_document=document,
            force=force,
            write_test=write_test,
        )
        result["personal_paths_redacted"] = redacted
        result["content_address"] = dump_sha
        result["classifications"] = len(document["assignments"])
        return result
    finally:
        temp.cleanup()


# --------------------------------------------------------------------------- CLI


def _add_model_flags(parser: argparse.ArgumentParser, *, from_dir_required: bool) -> None:
    parser.add_argument("--namespace", required=True)
    parser.add_argument(
        "--from-dir",
        required=from_dir_required,
        help="SketchUp export folder with model_dump.json / geom_probe.json / ... (.skp is ignored)",
    )
    parser.add_argument("--guidelines", help=f"repo-relative guideline markdown (default {SHARED_DEFAULTS['guidelines']})")
    parser.add_argument("--grouping-doc", help="repo-relative grouping workflow markdown written for this model")
    parser.add_argument("--classes", help=f"repo-relative class vocabulary (default {SHARED_DEFAULTS['classes']})")
    parser.add_argument("--force", action="store_true", help="replace differing captures / an already built registry entry")
    parser.add_argument("--no-test", action="store_true", help="do not emit tests/test_sketchup_ns_<ns>.py")
    parser.add_argument("--root", type=Path, help="repository root (default: this checkout)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sion_ingestion.sketchup_collection", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight", help="validate manifests, captures, overlays and outputs (read-only)")
    p.add_argument("--root", type=Path, help="repository root (default: this checkout)")
    p.add_argument("--namespace")
    p.add_argument("--build", action="store_true", help="also regenerate the export and compare (build --check)")
    p = sub.add_parser("manifest", help="print, write or check a namespace manifest")
    p.add_argument("--root", type=Path, help="repository root (default: this checkout)")
    p.add_argument("--namespace", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    p = sub.add_parser(
        "ingest",
        help="add one model: redact, content-address, classify explicit labels, build and check",
    )
    _add_model_flags(p, from_dir_required=True)
    p = sub.add_parser("scaffold", help="register a namespace, build + check it, write manifest and test stub")
    _add_model_flags(p, from_dir_required=False)
    args = parser.parse_args(argv)

    try:
        root = args.root.resolve() if args.root else ROOT
        if args.command == "preflight":
            findings = preflight(args.namespace, root, build=args.build)
            try:
                # A schema error is already a finding. Loading again must not replace that JSON with a traceback.
                namespaces = [args.namespace] if args.namespace else sorted(load_registry(root))
            except SketchUpAssetError:
                namespaces = []
            warnings = [w for ns in namespaces for w in preflight_warnings(ns, root)]
            report = {"ok": not findings, "findings": findings, "warnings": warnings}
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 0 if not findings else 1
        if args.command == "manifest":
            text = manifest_text(args.namespace, root)
            path = manifest_path(args.namespace, root)
            if args.check:
                same = path.exists() and path.read_bytes() == text.encode("utf-8")
                print(json.dumps({"namespace": args.namespace, "up_to_date": same}))
                return 0 if same else 1
            if args.write:
                path.write_bytes(text.encode("utf-8"))  # LF on every OS
                print(json.dumps({"written": _rel(path, root)}, ensure_ascii=False))
            else:
                sys.stdout.write(text)
            return 0
        model_kwargs = {
            "from_dir": Path(args.from_dir) if args.from_dir else None,
            "guidelines": args.guidelines,
            "grouping_doc": args.grouping_doc,
            "classes": args.classes,
            "force": args.force,
            "write_test": not args.no_test,
        }
        if args.command == "ingest":
            if model_kwargs["from_dir"] is None:
                raise CollectionError("--from-dir is required")
            result = ingest(args.namespace, root, **model_kwargs)
        else:
            result = scaffold(args.namespace, root, **model_kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["ok"] else 1
    except CollectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
