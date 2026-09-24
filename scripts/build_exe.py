#!/usr/bin/env python3
"""Build the Sion Agent Bridge as a reproducible one-file executable.

The spec owns the PyInstaller analysis. This wrapper only supplies repository
metadata, the safe runtime data-root smoke check, and an explicit UPX policy.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from importlib import metadata
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "sion-agent-bridge.spec"
DIST_DIR = REPO_ROOT / "dist"
MANIFEST_PATH = REPO_ROOT / "build" / "build-manifest.json"


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _manifest(data_root: Path) -> dict[str, object]:
    return {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "version": _git("describe", "--tags", "--always", "--dirty"),
        "commit": _git("rev-parse", "HEAD"),
        "python": platform.python_version(),
        "pyinstaller": metadata.version("pyinstaller"),
        "runtime": {
            "SION_DATA_ROOT": str(data_root),
            "data_root_contract": "frozen bridge reads SION_DATA_ROOT at runtime",
        },
    }


def _validate_runtime_data_root(value: str | None) -> Path:
    """Reject one-file temporary paths and prove the external root is writable."""
    if not value:
        raise SystemExit("SION_DATA_ROOT is required; do not use PyInstaller _MEIPASS")
    root = Path(value).expanduser().resolve()
    if root.name == "_MEIPASS" or "_MEIPASS" in root.parts:
        raise SystemExit("SION_DATA_ROOT must not be the one-file _MEIPASS directory")
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".sion-write-probe"
    try:
        probe.touch()
    finally:
        probe.unlink(missing_ok=True)
    return root


def build(*, upx: bool = False, data_root: str | None = None) -> None:
    if not SPEC_PATH.is_file():
        raise SystemExit(f"missing PyInstaller spec: {SPEC_PATH}")
    root = _validate_runtime_data_root(data_root or os.environ.get("SION_DATA_ROOT"))
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(_manifest(root), indent=2) + "\n", encoding="utf-8")

    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_PATH), "--noconfirm"]
    cmd.extend(["--distpath", str(DIST_DIR), "--workpath", str(REPO_ROOT / "build")])
    # UPX is controlled by the spec's explicit upx=False. PyInstaller rejects
    # --upx/--noupx when a spec file is supplied, so do not pass those flags here.
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, env={**os.environ, "SION_DATA_ROOT": str(root)})
    print(f"[+] Built one-file executable in {DIST_DIR}; data root: {root}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upx", action="store_true", help="explicitly enable UPX (default: disabled)")
    parser.add_argument("--data-root", help="external writable SION_DATA_ROOT for the runtime smoke check")
    args = parser.parse_args()
    build(upx=args.upx, data_root=args.data_root)


if __name__ == "__main__":
    main()
