"""CLI and sink boundary for the agent ontology bridge.

The DLP decision is made once, before *any* local or Drive sink is touched.  The
only payload accepted by sinks is the scanner's sanitized payload.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
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

    for path, content in ((out_json, json.dumps(export.model_dump(by_alias=True), indent=2, ensure_ascii=False)), (out_pg, pg), (out_graph, graph)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    from sion_api.db import build_engine, build_session_factory
    from sion_api.repository import seed_core_types
    engine = build_engine(args.db_url)
    with build_session_factory(engine)() as db:
        seed_core_types(db)
        result = import_map_export(db, export, already_scanned=decision)
    print(f"  [+] Local DB: {result.created_nodes} created, {result.skipped_nodes} skipped (existing)")

    drive_root = detect_google_drive_root()
    if not drive_root or not drive_root.exists():
        print("  [!] Google Drive root not detected. Saved to local runtime directory only.")
        return 0
    targets = [(out_pg, drive_root / "AEC-INTELLIGENCE/03_KNOWLEDGE_GRAPH/sion_pg_knowledge_graph.sql"), (out_json, drive_root / "AEC-INTELLIGENCE/03_KNOWLEDGE_GRAPH/sion_knowledge_graph.json"), (out_graph, drive_root / "AEC-INTELLIGENCE/09_AGENT_MEMORY/agent_knowledge_graph.md")]
    successes, failures, last_attempt = 0, [], "not_started"
    for src, dst in targets:
        last_attempt = dst.name
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            successes += 1
        except Exception:
            failures.append(dst.name)
    print(f"  [Drive] verified {successes}/{len(targets)} target(s); last_attempt={last_attempt}")
    if failures:
        print(
            f"  [!] partial sink state: {successes} succeeded, "
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
