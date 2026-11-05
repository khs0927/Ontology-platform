"""Check which 지음(ZIUM) standards from standards/zium/manifest.json exist on this PC.

Usage: python scripts/standards/zium_check.py [--json]
Read-only. Exit 0 always; prints found / missing / gap per stage.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "standards" / "zium" / "manifest.json"


def check(manifest=MANIFEST):
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    out = {}
    for stage, items in data["stages"].items():
        rows = []
        for it in items:
            p = it.get("path")
            if not p:
                state = "gap"
            elif p.startswith("repo:"):
                state = "found" if (ROOT / p[5:]).exists() else "missing"
            elif p.startswith("drive:"):
                state = "drive"
            else:
                state = "found" if Path(p).exists() else "missing"
            rows.append({"id": it["id"], "state": state, "path": p})
        out[stage] = rows
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    res = check()
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for stage, rows in res.items():
            print(f"[{stage}]")
            for r in rows:
                print(f"  {r['state']:7} {r['id']}  {r['path'] or ''}")
