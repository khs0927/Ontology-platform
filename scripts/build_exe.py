#!/usr/bin/env python3
"""Build the Sion Agent Bridge into a standalone executable (.exe on Windows)."""

from pathlib import Path
import argparse
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent


def build(distpath: Path | None = None, workpath: Path | None = None) -> Path:
    distpath = distpath or REPO_ROOT / "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    print(f"[*] Compiling standalone executable: {distpath / ('sion-agent-bridge' + suffix)}...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        "sion-agent-bridge",
        "--distpath",
        str(distpath),
        "--workpath",
        str(workpath or REPO_ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(workpath or REPO_ROOT / "build" / "pyinstaller"),
        "--paths",
        str(REPO_ROOT / "apps" / "api"),
        "--paths",
        str(REPO_ROOT / "packages" / "ingestion"),
        "--paths",
        str(REPO_ROOT / "packages" / "drive-store"),
        "--hidden-import",
        "sion_api",
        "--hidden-import",
        "sion_api.db",
        "--hidden-import",
        "sion_api.models",
        "--hidden-import",
        "sion_api.repository",
        "--hidden-import",
        "sion_ingestion",
        "--hidden-import",
        "sion_ingestion.agent_bridge",
        "--hidden-import",
        "sion_ingestion.map_import",
        "--hidden-import",
        "sion_ingestion.document_ingest",
        "--hidden-import",
        "sqlalchemy",
        "--hidden-import",
        "pydantic",
        str(REPO_ROOT / "scripts" / "run_agent_bridge.py"),
    ]
    subprocess.run(cmd, check=True)
    target = distpath / f"sion-agent-bridge{suffix}"
    print(f"\n[+] Build complete: {target}")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distpath", type=Path, help="output dir (default: bin/)")
    parser.add_argument("--workpath", type=Path, help="PyInstaller work/spec dir (default: build/pyinstaller)")
    ns = parser.parse_args()
    build(ns.distpath, ns.workpath)
