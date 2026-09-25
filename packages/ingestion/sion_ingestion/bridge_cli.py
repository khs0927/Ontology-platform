"""CLI and sink boundary for the agent ontology bridge.

The DLP decision is made once, before *any* local or Drive sink is touched.  The
only payload accepted by sinks is the scanner's sanitized payload.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

from sion_ingestion.agent_bridge import PROVIDER_REGISTRY, AgentOntologyBridge, detect_google_drive_root, get_device_id
from sion_ingestion.dlp import DLPDecision, scan_payload
from sion_ingestion.map_import import MapExport, import_map_export

REPO_ROOT = Path(__file__).resolve().parents[3]


def _os_data_root() -> Path:
    """Return a writable, OS-owned data location, never the checkout or bundle."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base).expanduser().resolve() / "SION"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "SION"
    return (Path.home() / ".local" / "share" / "SION").resolve()


def _data_root() -> Path:
    configured = os.environ.get("SION_DATA_ROOT")
    root = (Path(configured).expanduser() if configured else _os_data_root()).resolve()
    forbidden = {"_MEIPASS"}
    if any(part in forbidden for part in root.parts) or root == REPO_ROOT or REPO_ROOT in root.parents:
        raise ValueError("runtime data root must be external to the repository and _MEIPASS")
    return root


def _runtime_path(value: str | os.PathLike[str], root: Path) -> Path:
    """Resolve an explicit output only inside the configured data root."""
    raw = Path(value).expanduser()
    if ".." in raw.parts:
        raise ValueError("output paths may not contain '..'")
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("output path is outside the data root") from exc
    return candidate


def _staging_dir(root: Path, run_id: str) -> Path:
    """Return a run-scoped staging directory contained by the data root."""
    return _runtime_path(f"staging/{run_id}", root)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> tuple[str, int]:
    """Read a file back from disk and return its (sha256, byte size)."""
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def _write_staged(path: Path, content: str) -> tuple[str, int]:
    """Write one artifact into staging and return its expected (sha256, size)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return _digest(data), len(data)


def _verify_digest(path: Path, expected_digest: str, expected_size: int, label: str) -> None:
    """Fail closed unless the on-disk file matches the expected hash and size."""
    actual_digest, actual_size = _file_digest(path)
    if actual_digest != expected_digest or actual_size != expected_size:
        raise OSError(f"{label} read-back verification failed for '{path.name}'")


@contextlib.contextmanager
def _publish_lock(lock_path: Path):
    """Hold an exclusive publish lock so two writers cannot interleave a target."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"publish lock already held for '{lock_path.name}'") from exc
    try:
        record = {"pid": os.getpid(), "host": socket.gethostname(), "created": time.time()}
        os.write(handle, json.dumps(record).encode("utf-8"))
        os.close(handle)
        handle = -1
        yield
    finally:
        if handle != -1:
            os.close(handle)
        lock_path.unlink(missing_ok=True)


def _atomic_publish(src: Path, dst: Path, expected_digest: str, expected_size: int) -> None:
    """Publish a staged artifact: lock, temp copy, read-back verify, then replace."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    lock_path = dst.parent / f".{dst.name}.sion-publish.lock"
    tmp_path = dst.parent / f".{dst.name}.sion-publish.tmp"
    with _publish_lock(lock_path):
        try:
            shutil.copy2(src, tmp_path)
            _verify_digest(tmp_path, expected_digest, expected_size, "staging copy")
            os.replace(tmp_path, dst)
        finally:
            tmp_path.unlink(missing_ok=True)


def _safe_dlp_log(decision: DLPDecision) -> None:
    """Log counts and classifications only; never paths, values, or findings."""
    if decision.allowed:
        print("  [DLP] payload allowed")
    else:
        count = len(decision.findings)
        print(f"  [DLP] payload blocked ({count} finding(s)); no sinks written")


def run_cycle(args: argparse.Namespace, providers: list[str], limit_val: int | None) -> int:
    device_id = get_device_id()
    print(f"[*] [{time.strftime('%Y-%m-%d %H:%M:%S')}] Running sync cycle on device '{device_id}'...")
    sessions = []
    for provider in providers:
        reader_cls = PROVIDER_REGISTRY.get(provider)
        if reader_cls:
            found = reader_cls().discover(limit=limit_val)
            sessions.extend(found)
            print(f"  - {provider}: discovered {len(found)} session(s)")
    if not sessions:
        print("[!] No sessions found to import.")
        return 2

    bridge = AgentOntologyBridge()
    raw_export = bridge.convert_sessions_to_map_export(sessions, source_label=f"agent-bridge:{','.join(providers)}:{device_id}")
    root = _data_root()
    # before_all_sinks: scan the complete serialized MapExport, not individual fields.
    decision = scan_payload(raw_export.model_dump(by_alias=True), cwd=root)
    _safe_dlp_log(decision)
    if not decision.allowed and (
        decision.action != "tokenized" or not isinstance(decision.sanitized_payload, dict)
    ):
        return 1
    try:
        export = MapExport.model_validate(decision.sanitized_payload)
    except Exception:
        print("  [!] DLP sanitized payload failed MapExport validation; no sinks written.")
        return 1

    print(f"  -> Generated {len(export.nodes)} ontology entities and {len(export.edges)} relations.")
    out_json = _runtime_path(args.export_out, root)
    pg = bridge.export_to_postgres_sql(export)
    out_pg = _runtime_path(args.pg_out, root)
    graph = f"# Multi-Agent Conversation Knowledge Graph ({device_id})\n\n```mermaid\n{bridge.generate_mermaid_graph(export, max_nodes=80)}\n```\n"
    out_graph = _runtime_path(args.graph_out, root)

    # Dry-run is a read-only boundary: do not create dirs, files, DB, or Drive targets.
    if args.dry_run:
        print("[*] Dry run complete. Database and Drive were not modified.")
        return 0

    run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
    staging = _staging_dir(root, run_id)
    artifacts = (
        ("export.json", json.dumps(export.model_dump(by_alias=True), indent=2, ensure_ascii=False)),
        ("export.sql", pg),
        ("export.md", graph),
    )
    staged: dict[str, tuple[Path, str, int]] = {}
    try:
        for name, content in artifacts:
            digest, size = _write_staged(staging / name, content)
            _verify_digest(staging / name, digest, size, "staging")
            staged[name] = (staging / name, digest, size)
    except OSError as exc:
        print(f"  [!] staging failed: {exc}; no sinks published")
        shutil.rmtree(staging, ignore_errors=True)
        return 1
    print(f"  [stage] verified {len(staged)} artifact(s) in staging ({staging.name})")

    # The DB import is the commit point: external sinks are published only after it succeeds.
    try:
        from sion_api.db import build_engine, build_session_factory
        from sion_api.repository import seed_core_types
        engine = build_engine(args.db_url)
        with build_session_factory(engine)() as db:
            seed_core_types(db)
            result = import_map_export(db, export, already_scanned=decision)
    except Exception as exc:
        print(f"  [!] DB import failed: {type(exc).__name__}; no sinks published")
        shutil.rmtree(staging, ignore_errors=True)
        return 1
    print(f"  [+] Local DB: {result.created_nodes} created, {result.skipped_nodes} skipped (existing)")

    local_targets = (("export.json", out_json), ("export.sql", out_pg), ("export.md", out_graph))
    try:
        for name, dst in local_targets:
            src, digest, size = staged[name]
            _atomic_publish(src, dst, digest, size)
    except Exception as exc:
        print(f"  [!] local publish failed: {type(exc).__name__}; Drive not attempted")
        shutil.rmtree(staging, ignore_errors=True)
        return 1
    print(f"  [local] published {len(local_targets)} artifact(s)")

    drive_root = detect_google_drive_root()
    if not drive_root or not drive_root.exists():
        print("  [!] Google Drive root not detected. Saved to local runtime directory only.")
        shutil.rmtree(staging, ignore_errors=True)
        return 0
    targets = [
        ("export.sql", drive_root / "AEC-INTELLIGENCE/03_KNOWLEDGE_GRAPH/sion_pg_knowledge_graph.sql"),
        ("export.json", drive_root / "AEC-INTELLIGENCE/03_KNOWLEDGE_GRAPH/sion_knowledge_graph.json"),
        ("export.md", drive_root / "AEC-INTELLIGENCE/09_AGENT_MEMORY/agent_knowledge_graph.md"),
    ]
    successes, failures, last_attempt = 0, [], "not_started"
    for name, dst in targets:
        last_attempt = dst.name
        src, digest, size = staged[name]
        try:
            _atomic_publish(src, dst, digest, size)
            successes += 1
        except Exception:
            failures.append(dst.name)
    print(f"  [Drive] verified {successes}/{len(targets)} target(s); last_attempt={last_attempt}")
    shutil.rmtree(staging, ignore_errors=True)
    if failures:
        print(
            f"  [!] partial_failure: {successes} succeeded, "
            f"{len(failures)} failed; last_attempt={last_attempt}"
        )
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automated cross-device multi-agent conversation session bridge.")
    parser.add_argument("--provider", choices=["antigravity", "codex", "claude", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export-out", default="agent_export.json")
    parser.add_argument("--pg-out", default="sion_pg_knowledge_graph.sql")
    parser.add_argument("--graph-out", default="agent_graph.md")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _data_root()
    if args.db_url is None:
        args.db_url = f"sqlite:///{root / 'runtime' / 'sion.db'}"
    elif args.db_url.startswith("sqlite:///"):
        db_path = _runtime_path(args.db_url.removeprefix("sqlite:///"), root)
        args.db_url = f"sqlite:///{db_path}"
    providers = ["antigravity", "codex", "claude"] if args.provider == "all" else [args.provider]
    if args.daemon:
        while True:
            code = run_cycle(args, providers, None if args.limit <= 0 else args.limit)
            if code:
                return code
            time.sleep(args.interval)
    code = run_cycle(args, providers, None if args.limit <= 0 else args.limit)
    if code == 0:
        print("\n[SUCCESS] Completed automated multi-agent session bridge sync.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
