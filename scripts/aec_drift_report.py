"""Read-only SHA-256 inventory for legacy Ontology vs bundled AEC source code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

SOURCE_DIRS = ("src", "tests", "library", "extensions")
SUFFIXES = frozenset((".py", ".json", ".yaml", ".yml", ".toml", ".md", ".sql", ".ps1", ".sh", ".ttl", ".txt", ".dcl", ".lsp"))
SKIP_DIRS = frozenset((".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"))


def inventory(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise ValueError("source root must exist")
    result: dict[str, str] = {}
    for directory in SOURCE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for file in sorted(base.rglob("*")):
            relative = file.relative_to(root)
            if any(part in SKIP_DIRS or part.startswith(".") for part in relative.parts):
                continue
            if file.suffix.lower() not in SUFFIXES or not file.is_file() or file.is_symlink():
                continue
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[relative.as_posix()] = digest.hexdigest()
    return result


def compare(upstream: dict[str, str], bundled: dict[str, str]) -> dict:
    rows = []
    for path in sorted(upstream.keys() | bundled.keys()):
        u, b = upstream.get(path), bundled.get(path)
        state = ("bundled_only" if u is None else "upstream_only" if b is None else "modified" if u != b else "identical")
        rows.append({"path": path, "state": state, "upstream_sha256": u, "bundled_sha256": b})
    counts = Counter(row["state"] for row in rows)
    return {
        "contract": "aec-drift-inventory/1",
        "source_dirs": SOURCE_DIRS,
        "counts": {key: counts[key] for key in ("identical", "modified", "upstream_only", "bundled_only")},
        "files": rows,
        "safe_to_apply_automatically": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--bundled", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if (args.output.resolve().is_relative_to(args.upstream.resolve())
            or args.output.resolve().is_relative_to(args.bundled.resolve())):
        parser.error("output must be outside both source directories")
    report = compare(inventory(args.upstream), inventory(args.bundled))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("AEC source drift:", report["counts"], "output:", args.output)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        changed = [r for r in report["files"] if r["state"] != "identical"]
        with open(summary, "a", encoding="utf-8") as sink:
            sink.write("## AEC upstream vs bundled drift (read-only)\n\n")
            for name, total in report["counts"].items():
                sink.write(f"- {name}: {total}\n")
            sink.write("\nFirst 50 changed paths (content not included):\n\n")
            for row in changed[:50]:
                safe = row["path"].replace("|", "-").replace("<", "&lt;").replace("\n", " ")
                sink.write(f"- {safe} : {row['state']}\n")
            sink.write("\nNo patches, merges or branch protections changed.\n")
    return int(args.strict and any(report["counts"][k] for k in ("modified", "upstream_only", "bundled_only")))


if __name__ == "__main__":
    raise SystemExit(main())
