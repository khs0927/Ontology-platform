"""Read-only bootstrap snapshot manifests (issue #71, step B).

Given exported data (``sion-map-export/v1`` graph JSON, evidence JSONL, SQLite snapshot files or
any other plain file) under one *root* directory, :func:`create_manifest` describes it without
changing it:

* per file: root-relative ``source_uri``, byte size and SHA-256;
* SQLite files (detected by header): opened with ``file:...?mode=ro&immutable=1`` plus
  ``PRAGMA query_only``,
  row counts per table, ``user_version``, recorded core migrations (``sion_schema_migrations``,
  ``schema_migrations``, ``alembic_version`` when present) and a fingerprint of ``sqlite_master``;
* ``sion-map-export/v1`` JSON: node/edge counts (an export whose ``expected_*_count`` disagrees
  with its content is refused);
* ``.jsonl``: record count.

:func:`verify_manifest` recomputes everything and returns the mismatches; the CLI exits non-zero
on any of them (fail closed). The manifest also records its root-relative ``sources``; verify walks
them again and reports any file that is not listed (added after the manifest was made).

Safety rules, all enforced here rather than left to the caller:

* sources are only ever opened for reading; the manifest may not be written inside a source;
  SQLite files are opened ``immutable=1`` so that a WAL-mode database does not get ``-shm``/``-wal``
  files created next to it (safe because the file is hashed before and after it is read);
* every file is hashed before and after it is inspected, so a source that changes while the
  manifest is built is an error, not a silently inconsistent snapshot;
* a SQLite file with a non-empty ``-wal``/``-journal`` sidecar is a live database and is refused
  (take a consistent snapshot first: ``python -m sion_api.drive_export snapshot``);
* CAD originals (``.dwg``, ``.dxf``, ``.skp`` and their backups) are refused unless
  ``allow_cad_hash_only`` is set, and even then only their size and SHA-256 are recorded;
* secrets (``.env*``, keys, credential/token JSON) are refused when named explicitly and skipped
  (counted, not named) inside directories; VCS/cache directories and symlinks are skipped;
* the manifest records no absolute paths, host names or user names: only root-relative paths.

Usage::

    python -m sion_drive_store.bootstrap_snapshot create --root <export-dir> \\
        --created-at 2026-11-05T00:00:00Z --out <manifest.json> [--allow-cad-hash-only] [SOURCE ...]
    python -m sion_drive_store.bootstrap_snapshot verify <manifest.json> --root <export-dir>
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SCHEMA = "sion-bootstrap-snapshot/v1"
MAP_EXPORT_SCHEMA = "sion-map-export/v1"
SQLITE_MAGIC = b"SQLite format 3\x00"
CHUNK = 1024 * 1024

CAD_SUFFIXES = frozenset({".dwg", ".dxf", ".skp", ".skb", ".bak", ".dwl", ".dwl2"})
# ``.bak`` is AutoCAD's drawing backup; treat it as a CAD original too (fail closed).
SECRET_PATTERNS = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "*credentials*.json",
    "*client_secret*.json",
    "*service-account*.json",
    "*service_account*.json",
    "token*.json",
    "*.token",
    ".netrc",
    ".pgpass",
    ".npmrc",
    ".pypirc",
)
SKIP_DIRS = frozenset(
    {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".ruff_cache",
     ".mypy_cache", ".idea", ".vscode", ".cache"}
)
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
MIGRATION_TABLES = ("sion_schema_migrations", "schema_migrations")


class SnapshotError(RuntimeError):
    """The snapshot cannot be taken safely; nothing was written."""


@dataclass
class _Walk:
    files: list[Path] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1


# --------------------------------------------------------------------------- classification


def is_secret(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in SECRET_PATTERNS)


def is_cad_original(name: str) -> bool:
    return PurePosixPath(name.lower()).suffix in CAD_SUFFIXES


def is_sqlite_sidecar(name: str) -> bool:
    return name.lower().endswith(SQLITE_SIDECARS)


def validate_created_at(value: str) -> str:
    """``created_at`` is passed in (reproducible manifests) and must be timezone-aware ISO-8601."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"created_at is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SnapshotError("created_at must carry a timezone (e.g. 2026-11-05T00:00:00Z)")
    return value


# --------------------------------------------------------------------------- hashing & inspection


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _is_sqlite(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sqlite_readonly_uri(path: Path) -> str:
    """``file:`` URI opening ``path`` read-only (``?`` and ``#`` in the path are percent-encoded).

    ``immutable=1`` stops SQLite from creating ``-shm``/``-wal`` files next to a WAL-mode database,
    which ``mode=ro`` alone still does. A non-empty ``-wal`` is refused before opening, and the file
    is hashed before and after it is read, so nothing is hidden by skipping SQLite's locking.
    """
    return path.resolve().as_uri() + "?mode=ro&immutable=1"


def inspect_sqlite(path: Path) -> dict[str, Any]:
    for suffix in ("-wal", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists() and sidecar.stat().st_size > 0:
            raise SnapshotError(
                f"{path.name} has a non-empty {suffix} file: it looks like a live database. "
                "Snapshot it first (python -m sion_api.drive_export snapshot) and point at the copy."
            )
    try:
        conn = sqlite3.connect(sqlite_readonly_uri(path), uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - depends on the platform's sqlite build
        raise SnapshotError(f"cannot open {path.name} read-only: {exc}") from exc
    try:
        conn.execute("PRAGMA query_only = ON")
        master = conn.execute(
            "SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables = sorted(name for kind, name, _tbl, _sql in master if kind == "table")
        row_counts = {
            name: conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(name)}").fetchone()[0] for name in tables
        }
        fingerprint = hashlib.sha256(
            json.dumps(master, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        migrations: dict[str, list[str]] = {}
        for table in MIGRATION_TABLES:
            if table in row_counts:
                rows = conn.execute(f"SELECT version FROM {_quote_ident(table)} ORDER BY version").fetchall()
                migrations[table] = [str(row[0]) for row in rows]
        if "alembic_version" in row_counts:
            rows = conn.execute("SELECT version_num FROM alembic_version ORDER BY version_num").fetchall()
            migrations["alembic_version"] = [str(row[0]) for row in rows]
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.Error as exc:
        raise SnapshotError(f"cannot read {path.name}: {exc}") from exc
    finally:
        conn.close()
    if integrity != "ok":
        raise SnapshotError(f"{path.name} failed PRAGMA quick_check: {integrity}")
    return {
        "kind": "sqlite",
        "open_uri": f"file:{path.name}?mode=ro&immutable=1",
        "row_counts": row_counts,
        "schema": {
            "user_version": user_version,
            "migrations": migrations,
            "sqlite_master_sha256": fingerprint,
        },
    }


def inspect_map_export(document: dict[str, Any], name: str) -> dict[str, Any]:
    nodes, edges = document.get("nodes"), document.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise SnapshotError(f"{name}: {MAP_EXPORT_SCHEMA} without nodes/edges lists")
    for key, actual in (("expected_node_count", len(nodes)), ("expected_edge_count", len(edges))):
        expected = document.get(key)
        if expected is not None and expected != actual:
            raise SnapshotError(f"{name}: {key}={expected} but the export holds {actual}")
    result: dict[str, Any] = {
        "kind": "map-export",
        "schema": MAP_EXPORT_SCHEMA,
        "row_counts": {"nodes": len(nodes), "edges": len(edges)},
    }
    if isinstance(document.get("source"), str):
        result["export_source"] = document["source"]
    versions = sorted(
        {str(item["ontology_version"]) for item in (*nodes, *edges)
         if isinstance(item, dict) and item.get("ontology_version")}
    )
    if versions:
        result["ontology_versions"] = versions
    return result


def inspect_file(path: Path, *, allow_cad_hash_only: bool) -> dict[str, Any]:
    name = path.name
    if is_cad_original(name):
        if not allow_cad_hash_only:
            raise SnapshotError(
                f"{name} is a CAD original; snapshots never include CAD files "
                "(pass --allow-cad-hash-only to record its hash and size only)"
            )
        return {"kind": "cad-original", "hash_only": True}
    if _is_sqlite(path):
        return inspect_sqlite(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"kind": "file"}
        if isinstance(document, dict) and document.get("schema") == MAP_EXPORT_SCHEMA:
            return inspect_map_export(document, name)
        if isinstance(document, dict) and isinstance(document.get("schema"), str):
            return {"kind": "json", "schema": document["schema"]}
        return {"kind": "json"}
    if suffix == ".jsonl":
        count = 0
        with path.open("rb") as handle:
            for line in handle:
                if line.strip():
                    count += 1
        return {"kind": "jsonl", "row_counts": {"records": count}}
    return {"kind": "file"}


# --------------------------------------------------------------------------- walking


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise SnapshotError("every source must lie inside --root") from exc


def collect_sources(root: Path, sources: Iterable[str | Path]) -> _Walk:
    walk = _Walk()
    seen: set[Path] = set()
    for source in sources or ["."]:
        raw = Path(source)
        candidate = raw if raw.is_absolute() else root / raw
        if candidate.is_symlink():
            raise SnapshotError(f"{raw.name}: symlinks are not snapshotted")
        resolved = candidate.resolve()
        _relative(resolved, root)
        if not resolved.exists():
            raise SnapshotError(f"{_relative(resolved, root)}: does not exist")
        if resolved.is_file():
            if is_secret(resolved.name):
                raise SnapshotError(f"{resolved.name} looks like a secret; snapshots never include secrets")
            if is_sqlite_sidecar(resolved.name):
                raise SnapshotError(f"{resolved.name} is a live SQLite sidecar; snapshot the database instead")
            if resolved not in seen:
                seen.add(resolved)
                walk.files.append(resolved)
            continue
        for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
            base = Path(dirpath)
            kept = []
            for dirname in sorted(dirnames):
                if dirname in SKIP_DIRS:
                    walk.skip("vcs-or-cache")
                elif (base / dirname).is_symlink():
                    walk.skip("symlink")
                else:
                    kept.append(dirname)
            dirnames[:] = kept
            for filename in sorted(filenames):
                path = base / filename
                if path.is_symlink():
                    walk.skip("symlink")
                elif is_secret(filename):
                    walk.skip("secret")
                elif is_sqlite_sidecar(filename):
                    walk.skip("sqlite-sidecar")
                elif path.resolve() not in seen:
                    seen.add(path.resolve())
                    walk.files.append(path.resolve())
    walk.files.sort(key=lambda p: _relative(p, root))
    return walk


def _describe(path: Path, root: Path, *, allow_cad_hash_only: bool) -> dict[str, Any]:
    before = sha256_file(path)
    entry: dict[str, Any] = {"source_uri": "snapshot:" + _relative(path, root)}
    details = inspect_file(path, allow_cad_hash_only=allow_cad_hash_only)
    after = sha256_file(path)
    if before != after:
        raise SnapshotError(f"{path.name} changed while it was being read; stop the writer and retry")
    entry["sha256"], entry["size_bytes"] = before
    entry.update(details)
    return entry


def _content_digest(files: list[dict[str, Any]]) -> str:
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- public API


def create_manifest(
    root: str | Path,
    sources: Iterable[str | Path] = (),
    *,
    created_at: str,
    allow_cad_hash_only: bool = False,
) -> dict[str, Any]:
    """Describe ``sources`` (files or directories under ``root``) without modifying them."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise SnapshotError("--root must be an existing directory")
    created_at = validate_created_at(created_at)
    source_list = list(sources)
    walk = collect_sources(root_path, source_list)
    recorded_sources = sorted({
        _relative((Path(s) if Path(s).is_absolute() else root_path / s).resolve(), root_path) or "."
        for s in source_list or ["."]
    })
    if not walk.files:
        raise SnapshotError("no files to snapshot")
    files = [_describe(path, root_path, allow_cad_hash_only=allow_cad_hash_only) for path in walk.files]
    return {
        "schema": SCHEMA,
        "created_at": created_at,
        "options": {"allow_cad_hash_only": allow_cad_hash_only},
        "sources": recorded_sources,
        "file_count": len(files),
        "total_bytes": sum(item["size_bytes"] for item in files),
        "excluded": dict(sorted(walk.excluded.items())),
        "files": files,
        "content_sha256": _content_digest(files),
        "verify_command": "python -m sion_drive_store.bootstrap_snapshot verify <manifest.json> --root <root>",
    }


def write_manifest(manifest: dict[str, Any], out: str | Path, *, root: str | Path,
                   sources: Iterable[str | Path] = ()) -> Path:
    """Write ``manifest`` to a new file outside every source (never overwrites, never into a source)."""
    out_path = Path(out).absolute()
    root_path = Path(root).resolve()
    resolved_out = out_path.resolve()
    for source in list(sources) or ["."]:
        src = Path(source)
        src = (src if src.is_absolute() else root_path / src).resolve()
        if resolved_out == src or src in resolved_out.parents:
            raise SnapshotError("the manifest must not be written inside a snapshot source")
    if out_path.exists():
        raise SnapshotError("the manifest file already exists; choose a new name")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return out_path


def verify_manifest(manifest: dict[str, Any], root: str | Path) -> list[str]:
    """Recompute every recorded fact under ``root``; return mismatches (empty list = verified)."""
    problems: list[str] = []
    if manifest.get("schema") != SCHEMA:
        return [f"unsupported manifest schema {manifest.get('schema')!r} (expected {SCHEMA})"]
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return ["manifest lists no files"]
    if manifest.get("content_sha256") != _content_digest(files):
        problems.append("manifest content_sha256 does not match its file list (manifest edited?)")
    if manifest.get("file_count") != len(files):
        problems.append("manifest file_count does not match its file list")
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        return problems + ["--root is not a directory"]
    allow_cad = bool((manifest.get("options") or {}).get("allow_cad_hash_only"))
    for recorded in files:
        uri = recorded.get("source_uri", "")
        if not isinstance(uri, str) or not uri.startswith("snapshot:"):
            problems.append(f"unsupported source_uri {uri!r}")
            continue
        relative = PurePosixPath(uri.removeprefix("snapshot:"))
        if relative.is_absolute() or ".." in relative.parts:
            problems.append(f"{uri}: path escapes the root")
            continue
        path = root_path.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            problems.append(f"{uri}: missing")
            continue
        try:
            actual = _describe(path.resolve(), root_path, allow_cad_hash_only=allow_cad)
        except SnapshotError as exc:
            problems.append(f"{uri}: {exc}")
            continue
        for key in sorted(set(recorded) | set(actual)):
            if recorded.get(key) != actual.get(key):
                problems.append(f"{uri}: {key} differs (recorded {recorded.get(key)!r}, now {actual.get(key)!r})")
    problems.extend(_unlisted_files(manifest.get("sources"), files, root_path))
    return problems


def _unlisted_files(sources: Any, files: list[Any], root: Path) -> list[str]:
    """Files under the recorded ``sources`` that the manifest does not list (added afterwards)."""
    if sources is None:  # manifest without a source list: only the listed files can be checked
        return []
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        return ["manifest sources is not a list of root-relative paths"]
    problems: list[str] = []
    walk_sources: list[Path] = []
    for source in sources:
        relative = PurePosixPath(source)
        if relative.is_absolute() or ".." in relative.parts:
            problems.append(f"source {source!r}: path escapes the root")
        else:
            walk_sources.append(root.joinpath(*relative.parts))
    if problems:
        return problems
    try:
        walk = collect_sources(root, walk_sources)
    except SnapshotError as exc:
        return [f"cannot re-walk the recorded sources: {exc}"]
    listed = {item.get("source_uri") for item in files if isinstance(item, dict)}
    for path in walk.files:
        uri = "snapshot:" + _relative(path, root)
        if uri not in listed:
            problems.append(f"{uri}: not in the manifest (added after it was made)")
    return problems


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sion_drive_store.bootstrap_snapshot", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="build a read-only snapshot manifest")
    create.add_argument("sources", nargs="*", help="files or directories under --root (default: the whole root)")
    create.add_argument("--root", required=True, help="directory that source_uri paths are relative to")
    create.add_argument("--created-at", required=True, help="timezone-aware ISO-8601 timestamp to record")
    create.add_argument("--out", help="write the manifest here (new file, outside the sources); default: stdout")
    create.add_argument("--allow-cad-hash-only", action="store_true",
                        help="record CAD originals (.dwg/.dxf/.skp) by size and SHA-256 only instead of refusing")
    verify = sub.add_parser("verify", help="recompute a manifest and fail on any mismatch")
    verify.add_argument("manifest")
    verify.add_argument("--root", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            manifest = create_manifest(args.root, args.sources, created_at=args.created_at,
                                       allow_cad_hash_only=args.allow_cad_hash_only)
            if args.out:
                write_manifest(manifest, args.out, root=args.root, sources=args.sources)
                print(f"snapshot manifest: {manifest['file_count']} files, content_sha256 {manifest['content_sha256']}")
            else:
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0
        try:
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL cannot read manifest: {exc}", file=sys.stderr)
            return 1
        problems = verify_manifest(manifest, args.root)
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"OK {manifest['file_count']} files verified")
        return 0
    except SnapshotError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
