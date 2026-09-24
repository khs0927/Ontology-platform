#!/usr/bin/env python3
"""Compatibility wrapper for the installable Sion bridge CLI."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "ingestion"))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sion_ingestion.bridge_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
