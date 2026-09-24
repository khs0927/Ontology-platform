#!/usr/bin/env python3
"""Generate deterministic, unsigned release supply-chain metadata.

The command is deliberately conservative: it reads build artifacts and emits
metadata, but never modifies an artifact and never claims signing or verified
provenance.  SBOM generation is best effort through cyclonedx-py or syft.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tomllib
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def git(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                        stderr=subprocess.DEVNULL).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def version(name: str) -> str | None:
    try: return metadata.version(name)
    except metadata.PackageNotFoundError: return None

def artifact_records(paths: list[Path]) -> list[dict[str, object]]:
    out = []
    for p in sorted(paths, key=lambda x: x.name):
        if p.is_file() and not p.is_symlink():
            out.append({"name": p.name, "path": p.as_posix(), "sha256": sha256(p), "size": p.stat().st_size})
    return out

def dependencies() -> dict[str, str | None]:
    pyproject = ROOT / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        reqs = data.get("project", {}).get("dependencies", [])
    except (OSError, tomllib.TOMLDecodeError): reqs = []
    result = {}
    for req in reqs:
        if "==" in req: result[req.split("==", 1)[0].strip()] = req.rsplit("==", 1)[1].strip()
    return result

def alembic_head() -> str | None:
    try:
        return subprocess.check_output([sys.executable, "-m", "alembic", "heads"], cwd=ROOT,
                                        text=True, stderr=subprocess.DEVNULL).strip().splitlines()[-1].split()[0] or None
    except (OSError, subprocess.CalledProcessError, IndexError):
        revisions = sorted((ROOT / "migrations" / "versions").glob("*.py"))
        return revisions[-1].stem.split("_", 1)[0] if revisions else None

def resource_hashes() -> dict[str, str | None]:
    out = {}
    for p in sorted((ROOT / "apps" / "api" / "sion_api" / "resources").glob("*")):
        if p.is_file() and not p.is_symlink(): out[p.relative_to(ROOT).as_posix()] = sha256(p)
    return out

def sbom(root: Path, out: Path) -> str | None:
    tools = (["cyclonedx-py", "cyclonedx-py", "cyclonedx", "output", "--output-format", "json", "-o", str(out)], ["syft", "dir", str(root), "-o", "cyclonedx-json", "--file", str(out)])
    for cmd in tools:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if out.is_file(): return cmd[0]
            except (OSError, subprocess.CalledProcessError): pass
    return None

def safe_output(root: Path, name: str) -> Path:
    root = root.expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
    p = (root / name).resolve()
    if p.parent != root: raise ValueError(f"output path escapes output directory: {name}")
    return p

def generate(root: Path, output_dir: Path, artifacts: list[Path]) -> dict[str, object]:
    output_dir = output_dir.expanduser().resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    records = artifact_records(artifacts)
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    data: dict[str, object] = {
        "schema_version": "1.0",
        "repository": {"git_sha": commit, "git_dirty": dirty, "branch": git("rev-parse", "--abbrev-ref", "HEAD")},
        "artifacts": records, "artifact_count": len(records),
        "toolchain": {"python": sys.version.split()[0], "dependencies": dependencies(),
                      "pyinstaller": version("pyinstaller"), "build_backend": "setuptools.build_meta", "setuptools": version("setuptools")},
        "alembic_head": alembic_head(), "resource_hashes": resource_hashes(),
        "provenance": {"signature_status": "not_signed", "verified": False,
                       "builder": "scripts/generate-release-metadata.py", "source": "working-tree"}
    }
    sums = safe_output(output_dir, "SHA256SUMS")
    sums.write_text("".join(f"{r['sha256']}  {r['name']}\n" for r in records), encoding="utf-8")
    (safe_output(output_dir, "release-metadata.json")).write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (safe_output(output_dir, "provenance.json")).write_text(json.dumps(data["provenance"], sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return data

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT); p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--artifact", type=Path, action="append", default=[]); p.add_argument("--sbom", action="store_true")
    a = p.parse_args(); result = generate(a.root.resolve(), a.output_dir, a.artifact)
    if a.sbom:
        out = safe_output(a.output_dir.resolve(), "sbom.json"); tool = sbom(a.root.resolve(), out)
        if tool: result["sbom"] = {"format": "CycloneDX JSON", "generator": tool, "sha256": sha256(out)}
        else: result["sbom"] = {"format": "CycloneDX JSON", "status": "unavailable"}
    # refresh metadata with SBOM result when requested, without touching artifacts
    (safe_output(a.output_dir.resolve(), "release-metadata.json")).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
if __name__ == "__main__": main()
