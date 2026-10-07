#!/usr/bin/env python3
"""Standalone Hindsight advisory-memory runner.

This intentionally does not modify the existing agent bridge or Sion database.
It discovers sessions through the existing readers and only retains explicit
AgentSession.decisions when Hindsight is explicitly enabled.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "ingestion"))

from sion_ingestion.advisory_memory import HindsightAdvisoryMemory
from sion_ingestion.agent_bridge import PROVIDER_REGISTRY, AgentSession


def discover_sessions(providers: list[str], limit: int | None) -> list[AgentSession]:
    sessions: list[AgentSession] = []
    for provider in providers:
        reader_cls = PROVIDER_REGISTRY.get(provider)
        if reader_cls is None:
            continue
        sessions.extend(reader_cls().discover(limit=limit))
    return sessions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview, retain, recall, or reflect optional Hindsight advisory memory."
    )
    parser.add_argument(
        "--provider",
        choices=["antigravity", "codex", "claude", "all"],
        default="all",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--retain",
        action="store_true",
        help="Retain explicit durable decisions. Requires SION_HINDSIGHT_ENABLED=1.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview candidate counts and banks without network calls.",
    )
    parser.add_argument("--recall", metavar="QUERY")
    parser.add_argument("--reflect", metavar="QUERY")
    parser.add_argument(
        "--project",
        help="Project label for recall/reflect. Required with either option.",
    )
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if (args.recall or args.reflect) and not args.project:
        parser.error("--project is required with --recall or --reflect")
    if args.dry_run and (args.recall or args.reflect):
        parser.error("--dry-run cannot be combined with recall/reflect")

    memory = HindsightAdvisoryMemory.from_env()

    if args.recall:
        result = memory.recall(args.project, args.recall)
    elif args.reflect:
        result = memory.reflect(args.project, args.reflect)
    else:
        providers = (
            ["antigravity", "codex", "claude"]
            if args.provider == "all"
            else [args.provider]
        )
        limit = None if args.limit == 0 else args.limit
        sessions = discover_sessions(providers, limit)
        if args.dry_run or not args.retain:
            result = memory.preview(sessions)
            result["mode"] = "dry-run"
            result["session_count"] = len(sessions)
        else:
            result = memory.retain_sessions(sessions)
            result["mode"] = "retain"
            result["session_count"] = len(sessions)

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") != "DEGRADED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
