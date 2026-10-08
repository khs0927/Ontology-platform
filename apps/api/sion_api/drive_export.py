"""Google Drive storage root for platform assets, plus export-on-write of the live database.

The platform keeps its *assets* directly under one storage root, normally the Google Drive
for desktop folder ``<My Drive>/AEC-INTELLIGENCE/01_PROJECTS/SION-ONTOLOGY``:

* ``00_SOURCES/``: raw sources (SketchUp dumps, probes, renders) and the content-addressed
  artifact lake (``objects/sha256/..``, ``manifests/``)
* ``01_SNAPSHOTS/db/``: consistent snapshots of the live database (``sion-<UTC stamp>.db``
  plus ``sion-latest.db`` / ``sion-latest.sql`` for SQLite, ``.dump`` from ``pg_dump`` for
  PostgreSQL)
* ``02_EXPORTS/graph/``: the whole canonical graph as ``sion-map-export/v1`` JSON and the
  evidence rows as JSONL; ``02_EXPORTS/bootstrap/``: generated graph packs
* ``03_DOCS/``: knowledge documents (guidelines, workflows, architecture notes)
* ``09_AGENT_MEMORY/``: agent memory exports
* ``storage-manifest.json``: layout, last export, counts and SHA-256 of every exported file

The *live* database stays on a local disk (``SION_DATABASE_URL``). SQLite and PostgreSQL data
files must not live in a folder that a sync client streams or rewrites underneath them. Instead,
every committed write schedules a debounced export (``after_commit`` hook on the session
factory), so the Drive copies are refreshed on each change, not on a timer.

Configuration (environment):

* ``SION_STORAGE_ROOT``: the storage root itself, or
* ``SION_DRIVE_ROOT`` / ``GOOGLE_DRIVE_ROOT``: My Drive; the root becomes
  ``<drive>/AEC-INTELLIGENCE/01_PROJECTS/SION-ONTOLOGY``
* ``SION_DRIVE_EXPORT_ON_WRITE``: ``1`` (default when a root is set) or ``0``
* ``SION_DRIVE_EXPORT_DEBOUNCE_S``: seconds to wait for more writes (default 5)
* ``SION_DRIVE_SNAPSHOT_KEEP``: timestamped DB snapshots to keep (default 20)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, aliased, sessionmaker

from . import models

log = logging.getLogger(__name__)

PROJECT_DIR = Path("AEC-INTELLIGENCE") / "01_PROJECTS" / "SION-ONTOLOGY"
MANIFEST_SCHEMA = "sion-storage-manifest/v1"
SNAPSHOT_RE = re.compile(r"^sion-\d{8}T\d{6}Z\.(db|dump)$")
REPO_ROOT = Path(__file__).resolve().parents[3]

# repo-relative glob -> (layout attribute, repo prefix to strip, destination prefix)
ASSET_RULES: tuple[tuple[str, str, str, str], ...] = (
    ("data/sources/sketchup/**/*", "sources", "data/sources", ""),
    ("data/sources/PROVENANCE.md", "sources", "data/sources", ""),
    ("scripts/sketchup/*", "sources", "scripts/sketchup", "sketchup/scripts"),
    ("data/bootstrap/*.json", "exports_bootstrap", "data/bootstrap", ""),
    ("docs/sketchup/*.md", "docs", "docs", ""),
    ("docs/SKETCHUP_KNOWLEDGE.md", "docs", "docs", ""),
    ("docs/GRAPHRAG.md", "docs", "docs", ""),
    ("docs/DATABASE.md", "docs", "docs", ""),
    ("docs/STORAGE.md", "docs", "docs", ""),
    ("docs/SYNC_ARCHITECTURE.md", "docs", "docs", ""),
)


def _truthy(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def _replace_into(source: Path, destination: Path) -> None:
    """Copy ``source`` next to ``destination`` under a temporary name, then rename over it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _write_text(destination: Path, text: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp_name, destination)
    finally:
        Path(temp_name).unlink(missing_ok=True)


@dataclass(frozen=True)
class StorageLayout:
    """Folder layout under the platform storage root (normally on Google Drive)."""

    root: Path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> StorageLayout | None:
        env = os.environ if environ is None else environ
        explicit = (env.get("SION_STORAGE_ROOT") or "").strip()
        if explicit:
            return cls(Path(explicit).expanduser())
        for key in ("SION_DRIVE_ROOT", "GOOGLE_DRIVE_ROOT"):
            value = (env.get(key) or "").strip()
            if value:
                return cls(Path(value).expanduser() / PROJECT_DIR)
        return None

    @property
    def sources(self) -> Path:
        return self.root / "00_SOURCES"

    @property
    def snapshots_db(self) -> Path:
        return self.root / "01_SNAPSHOTS" / "db"

    @property
    def exports_graph(self) -> Path:
        return self.root / "02_EXPORTS" / "graph"

    @property
    def exports_bootstrap(self) -> Path:
        return self.root / "02_EXPORTS" / "bootstrap"

    @property
    def docs(self) -> Path:
        return self.root / "03_DOCS"

    @property
    def agent_memory(self) -> Path:
        return self.root / "09_AGENT_MEMORY"

    @property
    def manifest(self) -> Path:
        return self.root / "storage-manifest.json"

    def folders(self) -> dict[str, Path]:
        return {
            "sources": self.sources,
            "snapshots_db": self.snapshots_db,
            "exports_graph": self.exports_graph,
            "exports_bootstrap": self.exports_bootstrap,
            "docs": self.docs,
            "agent_memory": self.agent_memory,
        }

    def ensure(self) -> None:
        for path in self.folders().values():
            path.mkdir(parents=True, exist_ok=True)

    def describe(self) -> dict[str, str]:
        return {"root": str(self.root), **{k: str(v) for k, v in self.folders().items()}}


# --------------------------------------------------------------------------- manifest


def _read_manifest(layout: StorageLayout) -> dict[str, Any]:
    try:
        return json.loads(layout.manifest.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _update_manifest(layout: StorageLayout, section: str, payload: dict[str, Any]) -> None:
    manifest = _read_manifest(layout)
    manifest.update({"schema": MANIFEST_SCHEMA, "layout": layout.describe(), section: payload})
    _write_text(layout.manifest, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


# --------------------------------------------------------------------------- graph export


def graph_export_document(session: Session, *, source: str) -> dict[str, Any]:
    """Every entity and relation as a re-importable ``sion-map-export/v1`` document."""
    nodes = [
        {
            "stable_key": e.stable_key,
            "entity_type_id": e.entity_type_id,
            "name": e.name,
            "category": e.category,
            "description": e.description,
            "external_uri": e.external_uri,
            "properties": e.properties or {},
            "ontology_version": e.ontology_version,
        }
        for e in session.scalars(select(models.Entity).order_by(models.Entity.stable_key))
    ]
    src, tgt = aliased(models.Entity), aliased(models.Entity)
    rows = session.execute(
        select(models.Relation, src.stable_key, tgt.stable_key)
        .join(src, models.Relation.source_entity_id == src.id)
        .join(tgt, models.Relation.target_entity_id == tgt.id)
        .order_by(models.Relation.stable_key)
    )
    edges = [
        {
            "stable_key": r.stable_key,
            "source_stable_key": s,
            "target_stable_key": t,
            "relation_type_id": r.relation_type_id,
            "confidence": r.confidence,
            "verification_state": r.verification_state,
            "source_kind": r.source_kind,
            "ontology_version": r.ontology_version,
            "properties": r.properties or {},
        }
        for r, s, t in rows
    ]
    return {
        "schema": "sion-map-export/v1",
        "source": source,
        "expected_node_count": len(nodes),
        "expected_edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def evidence_jsonl(session: Session) -> tuple[str, int]:
    ent, rel = aliased(models.Entity), aliased(models.Relation)
    rows = session.execute(
        select(models.Evidence, ent.stable_key, rel.stable_key)
        .outerjoin(ent, models.Evidence.entity_id == ent.id)
        .outerjoin(rel, models.Evidence.relation_id == rel.id)
        .order_by(ent.stable_key, rel.stable_key, models.Evidence.source_uri, models.Evidence.source_locator)
    )
    lines = []
    for ev, entity_key, relation_key in rows:
        lines.append(
            json.dumps(
                {
                    "entity_stable_key": entity_key,
                    "relation_stable_key": relation_key,
                    "source_uri": ev.source_uri,
                    "source_locator": ev.source_locator,
                    "excerpt_hash": ev.excerpt_hash,
                    "confidence": ev.confidence,
                    "verification_state": ev.verification_state,
                    "extractor": ev.extractor,
                    "model": ev.model,
                    "properties": ev.properties or {},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return "".join(line + "\n" for line in lines), len(lines)


# --------------------------------------------------------------------------- database snapshot


def _sqlite_path(engine: Engine) -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def _snapshot_sqlite(engine: Engine, layout: StorageLayout, stamp: str) -> dict[str, Any]:
    path = _sqlite_path(engine)
    with tempfile.TemporaryDirectory(prefix="sion-snapshot-") as tmp:
        local = Path(tmp) / "snapshot.db"
        target = sqlite3.connect(local)
        try:
            if path is not None:
                source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                try:
                    source.backup(target)
                finally:
                    source.close()
            else:  # in-memory database (tests): back up through the engine's own connection
                raw = engine.raw_connection()
                try:
                    raw.driver_connection.backup(target)
                finally:
                    raw.close()
            sql_dump = "\n".join(target.iterdump()) + "\n"
        finally:
            target.close()
        stamped = layout.snapshots_db / f"sion-{stamp}.db"
        _replace_into(local, stamped)
        _replace_into(local, layout.snapshots_db / "sion-latest.db")
    _write_text(layout.snapshots_db / "sion-latest.sql", sql_dump)
    return {"kind": "sqlite-backup", "file": stamped.name, "latest": ["sion-latest.db", "sion-latest.sql"]}


def _snapshot_postgres(engine: Engine, layout: StorageLayout, stamp: str) -> dict[str, Any]:
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        return {"kind": "pg_dump", "skipped": "pg_dump not on PATH"}
    url = engine.url
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    with tempfile.TemporaryDirectory(prefix="sion-snapshot-") as tmp:
        local = Path(tmp) / "snapshot.dump"
        args = [pg_dump, "-Fc", "-f", str(local), "-d", url.database or ""]
        if url.host:
            args += ["-h", url.host]
        if url.port:
            args += ["-p", str(url.port)]
        if url.username:
            args += ["-U", url.username]
        subprocess.run(args, check=True, env=env, capture_output=True)
        stamped = layout.snapshots_db / f"sion-{stamp}.dump"
        _replace_into(local, stamped)
        _replace_into(local, layout.snapshots_db / "sion-latest.dump")
    return {"kind": "pg_dump", "file": stamped.name, "latest": ["sion-latest.dump"]}


def _prune_snapshots(layout: StorageLayout, keep: int) -> list[str]:
    """Delete the oldest timestamped snapshots written by this module (never anything else)."""
    if keep <= 0 or not layout.snapshots_db.exists():
        return []
    stamped = sorted(p for p in layout.snapshots_db.iterdir() if p.is_file() and SNAPSHOT_RE.match(p.name))
    removed = []
    for old in stamped[:-keep]:
        old.unlink()
        removed.append(old.name)
    return removed


def export_snapshot(
    engine: Engine,
    layout: StorageLayout,
    *,
    reason: str = "manual",
    keep: int = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write a DB snapshot, the full graph export and the evidence rows under ``layout``."""
    layout.ensure()
    stamp = _stamp(now)
    if engine.dialect.name == "sqlite":
        snapshot = _snapshot_sqlite(engine, layout, stamp)
    elif engine.dialect.name == "postgresql":
        snapshot = _snapshot_postgres(engine, layout, stamp)
    else:
        snapshot = {"kind": engine.dialect.name, "skipped": "no snapshot method"}
    with Session(engine) as session:
        graph = graph_export_document(session, source=f"sion-db:{engine.url.render_as_string(hide_password=True)}")
        evidence, evidence_count = evidence_jsonl(session)
    graph_path = layout.exports_graph / "sion-graph-latest.json"
    evidence_path = layout.exports_graph / "sion-evidence-latest.jsonl"
    _write_text(graph_path, json.dumps(graph, ensure_ascii=False, indent=2) + "\n")
    _write_text(evidence_path, evidence)
    removed = _prune_snapshots(layout, keep)
    files = [graph_path, evidence_path]
    for name in snapshot.get("latest", []):
        files.append(layout.snapshots_db / name)
    result = {
        "stamp": stamp,
        "reason": reason,
        "database": engine.url.render_as_string(hide_password=True),
        "snapshot": snapshot,
        "counts": {"entities": len(graph["nodes"]), "relations": len(graph["edges"]), "evidence": evidence_count},
        "files": {str(p.relative_to(layout.root).as_posix()): _sha256(p) for p in files if p.exists()},
        "pruned_snapshots": removed,
    }
    _update_manifest(layout, "last_export", result)
    return result


# --------------------------------------------------------------------------- export on write


class DriveExporter:
    """Debounced exporter: many writes in a burst produce one export."""

    def __init__(self, engine: Engine, layout: StorageLayout, *, debounce_s: float = 5.0, keep: int = 20) -> None:
        self.engine = engine
        self.layout = layout
        self.debounce_s = debounce_s
        self.keep = keep
        self.last_result: dict[str, Any] | None = None
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._pending: str | None = None

    @classmethod
    def from_env(cls, engine: Engine, environ: Mapping[str, str] | None = None) -> DriveExporter | None:
        env = os.environ if environ is None else environ
        layout = StorageLayout.from_env(env)
        if layout is None or not _truthy(env.get("SION_DRIVE_EXPORT_ON_WRITE"), True):
            return None
        return cls(
            engine,
            layout,
            debounce_s=float(env.get("SION_DRIVE_EXPORT_DEBOUNCE_S") or 5.0),
            keep=int(env.get("SION_DRIVE_SNAPSHOT_KEEP") or 20),
        )

    def schedule(self, reason: str = "write") -> None:
        with self._lock:
            self._pending = reason
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_s, self._run_pending)
            self._timer.daemon = True
            self._timer.start()

    def _run_pending(self) -> None:
        with self._lock:
            reason, self._pending, self._timer = self._pending, None, None
        if reason is not None:
            self.run(reason)

    def run(self, reason: str = "manual") -> dict[str, Any] | None:
        with self._run_lock:
            try:
                self.last_result = export_snapshot(self.engine, self.layout, reason=reason, keep=self.keep)
                self.last_error = None
            except Exception as exc:  # the API keeps serving; the error is visible on /storage/status
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("drive export failed")
                return None
            return self.last_result

    def flush(self) -> None:
        """Run a pending export now (shutdown, tests)."""
        with self._lock:
            timer, reason = self._timer, self._pending
            self._timer, self._pending = None, None
        if timer is not None:
            timer.cancel()
        if reason is not None:
            self.run(reason)

    def status(self) -> dict[str, Any]:
        return {
            "layout": self.layout.describe(),
            "export_on_write": True,
            "debounce_s": self.debounce_s,
            "snapshot_keep": self.keep,
            "pending": self._pending is not None,
            "last_export": self.last_result,
            "last_error": self.last_error,
        }


def install_export_on_write(factory: sessionmaker, exporter: DriveExporter) -> None:
    """Schedule an export after every commit that flushed inserts, updates or deletes."""

    def _mark(session: Session, _context, _instances) -> None:
        if session.new or session.dirty or session.deleted:
            session.info["sion_drive_dirty"] = True

    def _after_commit(session: Session) -> None:
        if session.info.pop("sion_drive_dirty", False):
            exporter.schedule("commit")

    def _after_rollback(session: Session) -> None:
        session.info.pop("sion_drive_dirty", None)

    event.listen(factory, "before_flush", _mark)
    event.listen(factory, "after_commit", _after_commit)
    event.listen(factory, "after_soft_rollback", lambda session, _previous: _after_rollback(session))


def export_if_configured(engine: Engine, *, reason: str) -> dict[str, Any] | None:
    """For one-shot CLIs (imports): export right away when a storage root is configured."""
    exporter = DriveExporter.from_env(engine)
    return exporter.run(reason) if exporter is not None else None


# --------------------------------------------------------------------------- asset placement


def publish_assets(layout: StorageLayout, repo_root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """Place the repo's committed assets under the storage root (skips identical files, never deletes)."""
    placed: list[str] = []
    unchanged: list[str] = []
    seen: set[Path] = set()
    for pattern, attr, strip, prefix in ASSET_RULES:
        base: Path = getattr(layout, attr)
        for source in sorted(repo_root.glob(pattern)):
            if not source.is_file() or source in seen or "__pycache__" in source.parts:
                continue
            seen.add(source)
            destination = base / prefix / source.relative_to(repo_root / strip)
            if destination.exists() and destination.stat().st_size == source.stat().st_size:
                if _sha256(destination) == _sha256(source):
                    unchanged.append(destination.relative_to(layout.root).as_posix())
                    continue
            _replace_into(source, destination)
            placed.append(destination.relative_to(layout.root).as_posix())
    _update_manifest(
        layout,
        "last_publish",
        {"stamp": _stamp(), "repo_root": str(repo_root), "placed": len(placed), "unchanged": len(unchanged)},
    )
    return {"placed": placed, "unchanged": unchanged}


# --------------------------------------------------------------------------- CLI


def _layout_or_exit(args) -> StorageLayout:
    layout = StorageLayout(Path(args.storage_root)) if args.storage_root else StorageLayout.from_env()
    if layout is None:
        raise SystemExit("set SION_STORAGE_ROOT (or SION_DRIVE_ROOT) or pass --storage-root")
    return layout


def main(argv: Iterable[str] | None = None) -> int:
    from .config import load_settings
    from .db import build_engine

    parser = argparse.ArgumentParser(prog="python -m sion_api.drive_export", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("layout", "snapshot", "publish-assets"):
        p = sub.add_parser(name)
        p.add_argument("--storage-root")
        if name == "layout":
            p.add_argument("--create", action="store_true")
        if name == "snapshot":
            p.add_argument("--database-url")
            p.add_argument("--keep", type=int, default=None)
        if name == "publish-assets":
            p.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(list(argv) if argv is not None else None)
    layout = _layout_or_exit(args)
    if args.command == "layout":
        if args.create:
            layout.ensure()
        print(json.dumps({**layout.describe(), "exists": layout.root.exists()}, ensure_ascii=False, indent=2))
    elif args.command == "snapshot":
        engine = build_engine(args.database_url or load_settings().database_url)
        keep = args.keep if args.keep is not None else int(os.getenv("SION_DRIVE_SNAPSHOT_KEEP") or 20)
        print(json.dumps(export_snapshot(engine, layout, reason="cli", keep=keep), ensure_ascii=False, indent=2))
    else:
        result = publish_assets(layout, Path(args.repo_root))
        print(json.dumps({"placed": result["placed"], "unchanged": len(result["unchanged"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
