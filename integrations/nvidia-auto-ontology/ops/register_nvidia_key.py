"""Transfer NVIDIA API key from Doppler to GitHub Actions without displaying it.

Run on an authorized device that already has a logged-in Doppler CLI and gh.
The key is never printed, written to files, or passed as a command argument.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = "khs0927/Ontology-platform"
SECRET_NAME = "NVIDIA_API_KEY"
PROJECT = "ai-api-keys"
CONFIG = "prd"


def locate_doppler(explicit: str | None) -> str:
    candidates = [explicit, shutil.which("doppler")]
    if os.name == "nt":
        candidates.append(r"C:\CODE\permit-review-mcp\.tools\doppler.exe")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("Doppler CLI unavailable; pass --doppler PATH")


def child() -> int:
    key = os.environ.get(SECRET_NAME, "").strip()
    if not key.startswith("nvapi-") or len(key) < 25:
        print("NVIDIA_API_KEY is absent or invalid in Doppler ai-api-keys/prd")
        return 2
    if not shutil.which("gh"):
        print("GitHub CLI not found; install gh and run gh auth login first")
        return 3
    result = subprocess.run(
        ["gh", "secret", "set", SECRET_NAME, "--repo", REPO],
        input=key.encode("utf-8"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=45,
    )
    if result.returncode:
        print("GitHub secret registration failed; exit code", result.returncode)
        return 4
    check = subprocess.run(
        ["gh", "secret", "list", "--repo", REPO, "--json", "name"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=25,
    )
    if check.returncode or '"' + SECRET_NAME + '"' not in check.stdout:
        print("Secret write may have succeeded; name-only verification failed")
        return 5
    print(f"Confirmed {SECRET_NAME} exists in {REPO}. Secret value hidden.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Secure Doppler to GitHub key transfer")
    parser.add_argument("--doppler", help="Path to Doppler CLI if not on PATH")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child()
    try:
        doppler = locate_doppler(args.doppler)
    except RuntimeError as error:
        print(str(error))
        return 1
    cmd = [
        doppler, "run", "--project", PROJECT, "--config", CONFIG,
        "--", sys.executable, str(Path(__file__).resolve()), "--child",
    ]
    try:
        return subprocess.run(cmd, check=False, timeout=100).returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Doppler execution failed: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
