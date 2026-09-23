#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-/shared/sion-ontology-snapshots}"
STAMP="${SION_SNAPSHOT_STAMP:-$(date -u +%Y%m%d-%H%M%SZ)}"

cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "[ERROR] not a Git work tree: $ROOT" >&2
  exit 2
fi

# Snapshot the exact Git index, not transient caches or unstaged editor files.
TREE="$(git write-tree)"
NAME="sion-ontology-platform-${STAMP}"
ARCHIVE="$OUT_DIR/${NAME}.tar.gz"
MANIFEST="$OUT_DIR/${NAME}.manifest.json"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$OUT_DIR"

git archive --format=tar --prefix="${NAME}/" "$TREE" > "$TMP/archive.tar"
gzip -n -9 -c "$TMP/archive.tar" > "$ARCHIVE"

python3 - "$ROOT" "$TREE" "$ARCHIVE" "$MANIFEST" "$STAMP" <<'PY'
from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path

root=Path(sys.argv[1])
tree=sys.argv[2]
archive=Path(sys.argv[3])
manifest=Path(sys.argv[4])
stamp=sys.argv[5]

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()

paths=subprocess.check_output(
    ["git","-C",str(root),"ls-files","--stage","-z"]
)
entries=[]
for record in paths.split(b"\0"):
    if not record:
        continue
    meta,path=record.split(b"\t",1)
    mode,git_blob,stage=meta.decode().split()
    if stage != "0":
        raise SystemExit(f"unmerged index entry: {path!r}")
    rel=path.decode("utf-8")
    data=subprocess.check_output(["git","-C",str(root),"show",f":{rel}"])
    entries.append({
        "path":rel,
        "mode":mode,
        "git_blob":git_blob,
        "sha256":sha256_bytes(data),
        "byte_size":len(data),
    })

payload={
    "schema":"sion-project-snapshot/v1",
    "timestamp_utc":stamp,
    "source":"git-index",
    "git_tree":tree,
    "file_count":len(entries),
    "archive_name":archive.name,
    "archive_byte_size":archive.stat().st_size,
    "archive_sha256":"sha256:"+sha256_file(archive),
    "files":entries,
}
manifest.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({
    "git_tree":tree,
    "file_count":len(entries),
    "archive":str(archive),
    "archive_sha256":payload["archive_sha256"],
    "manifest":str(manifest),
},ensure_ascii=False))
PY
