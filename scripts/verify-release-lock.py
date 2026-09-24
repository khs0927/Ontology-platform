from __future__ import annotations

import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-release.lock"
PYPROJECT = ROOT / "pyproject.toml"
PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)(?P<extras>\[[^]]+\])?==(?P<version>[^ ]+)$")
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("--hash="):
            raise ValueError(f"unfixed or malformed lock line: {line}")
        digest = parts[1].removeprefix("--hash=")
        if not HASH.fullmatch(digest):
            raise ValueError(f"unfixed or malformed lock line: {line}")
        match = PIN.fullmatch(parts[0])
        if not match:
            raise ValueError(f"not an exact pin: {parts[0]}")
        key = (canonical(match.group("name")), match.group("extras") or "")
        if key in result:
            raise ValueError(f"duplicate lock entry: {key}")
        result[key] = (match.group("version"), digest)
    return result


def project_requirements(pyproject: Path = PYPROJECT) -> list[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data["project"]
    return project["dependencies"] + project.get("optional-dependencies", {}).get("test", []) + ["setuptools==84.0.0", "pyinstaller==6.22.3", "pgvector==0.5.0"]


def verify(lock: Path = LOCK, pyproject: Path = PYPROJECT) -> None:
    expected: dict[tuple[str, str], str] = {}
    for requirement in project_requirements(pyproject):
        match = PIN.fullmatch(requirement)
        if not match:
            raise ValueError(f"project requirement is not exact: {requirement}")
        expected[(canonical(match.group("name")), match.group("extras") or "")] = match.group("version")
    actual = parse_lock(lock)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    drift = sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k][0])
    no_hash = [key for key, (_, digest) in actual.items() if not HASH.fullmatch(digest)]
    if missing or extra or drift or no_hash:
        raise SystemExit(f"release lock failed: missing={missing} extra={extra} drift={drift} no_hash={no_hash}")
    print(f"release lock verified: {len(actual)} exact hash-pinned requirements")


if __name__ == "__main__":
    verify()
