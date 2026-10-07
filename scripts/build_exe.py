#!/usr/bin/env python3
"""Build script to compile the Sion Agent Bridge into a standalone Windows .exe"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def build():
    print("[*] Compiling standalone executable: bin/sion-agent-bridge.exe...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        "sion-agent-bridge",
        "--distpath",
        str(REPO_ROOT / "bin"),
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
        "sqlalchemy",
        "--hidden-import",
        "pydantic",
        str(REPO_ROOT / "scripts" / "run_agent_bridge.py"),
    ]
    subprocess.run(cmd, check=True)
    print("\n[+] Build complete: bin/sion-agent-bridge.exe")


if __name__ == "__main__":
    build()
