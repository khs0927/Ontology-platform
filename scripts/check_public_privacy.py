"""Check tracked public content without printing the matched private values."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = {
    "personal email": re.compile(rb"[A-Za-z0-9._%+-]+@(?:gmail\.com|naver\.com|hanmail\.net|daum\.net|hotmail\.com|outlook\.com)", re.I),
    "personal profile path": re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"\r\n]+)", re.I),
    "private Drive identifier": re.compile(rb"(?:drive\.google\.com/(?:file/d/|drive/folders/)|file id [`\"])([A-Za-z0-9_-]{20,})"),
    "embedded Drive identifier": re.compile(rb"[`\"](1[A-Za-z0-9_-]{24,44})[`\"]"),
}
PUBLIC_PROFILE_NAMES = {b"user", b"username", b"public", b"example", b"<user>", b"<username>"}


def violations(content: bytes) -> list[str]:
    found = []
    for category, pattern in PATTERNS.items():
        matches = list(pattern.finditer(content))
        if category == "personal profile path":
            matches = [m for m in matches if m[1].lower() not in PUBLIC_PROFILE_NAMES]
        if category == "embedded Drive identifier":
            matches = [m for m in matches if b"drive" in content.lower() and not re.fullmatch(rb"[a-f0-9]{40,64}", m[1])]
        if matches:
            found.append(category)
    return found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).split(b"\0")
    failures = 0
    for raw in names:
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = root / name
        if not path.is_file():
            continue
        for category in violations(path.read_bytes()):
            print(f"{name}: {category} (value withheld)")
            failures += 1
    print(f"Public privacy check: {failures} finding(s)")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
