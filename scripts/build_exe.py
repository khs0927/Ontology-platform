#!/usr/bin/env python3
"""Build script to compile the Sion Agent Bridge into a standalone Windows .exe"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def build(dist_dir: Path | None = None, name: str = "sion-agent-bridge"):
    dist_dir = Path(dist_dir) if dist_dir else REPO_ROOT / "bin"
    print(f"[*] Compiling standalone executable: {dist_dir / name}(.exe)...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(REPO_ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(REPO_ROOT / "build" / "pyinstaller"),
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
    print(f"\n[+] Build complete: {dist_dir / name}(.exe)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=None, help="output directory (default: bin/)")
    parser.add_argument("--name", default="sion-agent-bridge", help="executable base name")
    args = parser.parse_args(argv)
    build(args.dist, args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
