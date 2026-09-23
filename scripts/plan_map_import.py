#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from ontology_map_bridge import build_import_plan, load_map_export


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a structured Ontology Map export and emit a canonical dry-run import plan."
    )
    parser.add_argument("source", help="Path to ontology-map-export/v1 JSON")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    export = load_map_export(args.source)
    plan = build_import_plan(export)

    print(
        json.dumps(
            plan.model_dump(mode="json"),
            ensure_ascii=False,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
