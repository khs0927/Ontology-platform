#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _rel in ("apps/api", "packages/core", "packages/ingestion", "packages/cad", "packages/bim",
             "packages/cair", "packages/drive-store"):
    sys.path.insert(0, str(REPO_ROOT / _rel))

from sion_api.db import build_engine, build_session_factory
from sion_api.drive_export import StorageLayout, export_snapshot
from sion_api.repository import seed_core_types
from sion_ingestion.agent_bridge import (
    PROVIDER_REGISTRY,
    AgentOntologyBridge,
    AgentSession,
    detect_google_drive_root,
    get_device_id,
)
from sion_ingestion.map_import import import_map_export


def sync_cycle(args, providers: list[str], limit_val: int | None) -> None:
    device_id = get_device_id()
    print(f"\n[*] [{time.strftime('%Y-%m-%d %H:%M:%S')}] Running sync cycle on device '{device_id}'...")

    all_sessions: list[AgentSession] = []
    for prov in providers:
        reader_cls = PROVIDER_REGISTRY.get(prov)
        if reader_cls:
            reader = reader_cls()
            sessions = reader.discover(limit=limit_val)
            all_sessions.extend(sessions)
            print(f"  - {prov}: discovered {len(sessions)} session(s)")

    if not all_sessions:
        print("[!] No sessions found to import.")
        return

    bridge = AgentOntologyBridge()
    export = bridge.convert_sessions_to_map_export(
        all_sessions, source_label=f"agent-bridge:{','.join(providers)}:{device_id}"
    )

    print(f"  -> Generated {len(export.nodes)} ontology entities and {len(export.edges)} relations.")

    # 1. Save MapExport JSON
    out_json_path = REPO_ROOT / args.export_out
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(
        json.dumps(export.model_dump(by_alias=True), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 2. Save PostgreSQL SQL dump
    pg_sql = bridge.export_to_postgres_sql(export)
    out_pg_path = REPO_ROOT / args.pg_out
    out_pg_path.parent.mkdir(parents=True, exist_ok=True)
    out_pg_path.write_text(pg_sql, encoding="utf-8")

    # 3. Generate Mermaid Graph
    mermaid_code = bridge.generate_mermaid_graph(export, max_nodes=80)
    out_graph_path = REPO_ROOT / args.graph_out
    out_graph_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_content = f"# Multi-Agent Conversation Knowledge Graph ({device_id})\n\n```mermaid\n{mermaid_code}\n```\n"
    out_graph_path.write_text(markdown_content, encoding="utf-8")

    if args.dry_run:
        print("[*] Dry run complete. Database and Drive were not modified.")
        return

    # 4. Ingest into local SQLite DB
    engine = build_engine(args.db_url)
    session_factory = build_session_factory(engine)
    with session_factory() as db_session:
        seed_core_types(db_session)
        result = import_map_export(db_session, export)
        print(f"  [+] Local DB: {result.created_nodes} created, {result.skipped_nodes} skipped (existing)")

    # 5a. Storage root configured (SION_STORAGE_ROOT / SION_DRIVE_ROOT): write straight into it.
    #     The live DB file is never copied; a consistent snapshot + graph export is written instead.
    layout = StorageLayout.from_env()
    if layout is not None:
        layout.ensure()
        bridge_dir = layout.root / "02_EXPORTS" / "agent-bridge"
        bridge_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_json_path, bridge_dir / "sion_knowledge_graph.json")
        shutil.copyfile(out_pg_path, bridge_dir / "sion_pg_knowledge_graph.sql")
        shutil.copyfile(out_graph_path, layout.agent_memory / "agent_knowledge_graph.md")
        export_snapshot(engine, layout, reason="agent-bridge")
        print(f"  [+] Storage root updated: {layout.root}")
        return

    # 5b. Legacy: copy outputs to a detected Google Drive (no storage root configured)
    drive_root = detect_google_drive_root()
    if drive_root and drive_root.exists():
        print(f"  [*] Detected Google Drive at: {drive_root}")
        drive_kg = drive_root / "AEC-INTELLIGENCE" / "03_KNOWLEDGE_GRAPH"
        drive_mem = drive_root / "AEC-INTELLIGENCE" / "09_AGENT_MEMORY"
        drive_exp = drive_root / "AEC-INTELLIGENCE" / "10_EXPORTS"
        drive_snapshots = drive_root / ".CODE" / "_sync-v2" / "snapshots"
        drive_device = drive_root / ".CODE" / "_sync-v2" / "devices" / device_id / "exports"

        targets = [
            (out_pg_path, drive_kg / "sion_pg_knowledge_graph.sql"),
            (out_json_path, drive_kg / "sion_knowledge_graph.json"),
            (out_graph_path, drive_mem / "agent_knowledge_graph.md"),
            (out_pg_path, drive_exp / "sion_pg_knowledge_graph.sql"),
            (out_pg_path, drive_snapshots / "sion_pg_knowledge_graph.sql"),
            (out_pg_path, drive_device / "sion_pg_knowledge_graph.sql"),
            (out_json_path, drive_device / "sion_knowledge_graph.json"),
        ]

        if args.db_url.startswith("sqlite:///"):
            local_db_path = REPO_ROOT / args.db_url.removeprefix("sqlite:///")
            if local_db_path.exists():
                targets.append((local_db_path, drive_kg / "sion_knowledge.db"))
                targets.append((local_db_path, drive_device / "sion_knowledge.db"))

        for src, dst in targets:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except Exception as e:
                print(f"  [!] Drive sync error for {dst.name}: {e}")
        print("  [+] Google Drive synchronization complete.")
    else:
        print("  [!] Google Drive root not detected. Saved to local runtime directory only.")


def install_automated_task() -> None:
    """Register this script as a recurring automated background task on Windows or POSIX."""
    python_exe = sys.executable
    script_path = (REPO_ROOT / "scripts" / "run_agent_bridge.py").resolve()

    if sys.platform == "win32":
        task_name = "SionAgentOntologySync"
        cmd = [
            "schtasks",
            "/Create",
            "/F",
            "/SC", "MINUTE",
            "/MO", "15",
            "/TN", task_name,
            "/TR", f'"{python_exe}" "{script_path}"',
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(f"[+] Successfully installed Windows Scheduled Task: {task_name} (Runs every 15 mins)")
        except Exception as e:
            print(f"[!] Failed to register scheduled task: {e}")
    else:
        # Linux / macOS cron
        cron_line = f"*/15 * * * * \"{python_exe}\" \"{script_path}\" > /dev/null 2>&1\n"
        try:
            cur_cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
            if str(script_path) not in cur_cron:
                new_cron = cur_cron + cron_line
                subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)
                print("[+] Successfully added user cron job (Runs every 15 mins)")
            else:
                print("[*] Cron job is already installed.")
        except Exception as e:
            print(f"[!] Failed to configure cron job: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Automated cross-device multi-agent conversation session bridge."
    )
    parser.add_argument(
        "--provider",
        choices=["antigravity", "codex", "claude", "all"],
        default="all",
        help="Target agent provider (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max sessions per provider (0 = ALL available sessions, default: 0)",
    )
    parser.add_argument(
        "--db-url",
        default="sqlite:///runtime/sion.db",
        help="Database URL (default: sqlite:///runtime/sion.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview ontology export without writing to database or Drive",
    )
    parser.add_argument(
        "--export-out",
        type=str,
        default="runtime/agent_export.json",
        help="Save raw MapExport JSON to this path",
    )
    parser.add_argument(
        "--pg-out",
        type=str,
        default="runtime/sion_pg_knowledge_graph.sql",
        help="Save PostgreSQL dump to this path",
    )
    parser.add_argument(
        "--graph-out",
        type=str,
        default="runtime/agent_graph.md",
        help="Save Mermaid diagram to this path",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously in background, syncing on interval",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Interval in seconds for daemon mode (default: 300)",
    )
    parser.add_argument(
        "--install-task",
        action="store_true",
        help="Register a recurring background task on this OS to run automatically",
    )

    args = parser.parse_args()

    if args.install_task:
        install_automated_task()
        return

    providers = ["antigravity", "codex", "claude"] if args.provider == "all" else [args.provider]
    limit_val = None if args.limit <= 0 else args.limit

    if args.daemon:
        print(f"[*] Starting daemon mode (polling every {args.interval}s)... Press Ctrl+C to stop.")
        while True:
            try:
                sync_cycle(args, providers, limit_val)
            except Exception as e:
                print(f"[!] Error in sync cycle: {e}")
            time.sleep(args.interval)
    else:
        sync_cycle(args, providers, limit_val)
        print("\n[SUCCESS] Completed automated multi-agent session bridge sync.")


if __name__ == "__main__":
    main()
