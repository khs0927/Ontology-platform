#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from ontology_api.db import Database
from ontology_api.map_import import import_map
from ontology_map_bridge import load_map_export


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a structured Ontology Map export into the canonical knowledge database."
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="data/bootstrap/sion-map-production.json",
        help="Path to ontology-map-export/v1 JSON (default: data/bootstrap/sion-map-production.json)",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", "sqlite:///runtime/ontology.db"),
        help="Database connection URL (default: env DATABASE_URL or sqlite:///runtime/ontology.db)",
    )
    args = parser.parse_args()

    export = load_map_export(args.source)
    print(f"Loaded map export from {args.source}:")
    print(f"  Namespace: {export.namespace}")
    print(f"  Nodes: {len(export.nodes)}")
    print(f"  Relations: {len(export.relations)}")

    database = Database(args.db_url)
    database.initialize()

    with database.SessionLocal() as session:
        result = import_map(session, export)
        print("\nImport completed successfully:")
        print(f"  Namespace: {result.namespace}")
        print(f"  Entities created: {result.entities_created}")
        print(f"  Relations created: {result.relations_created}")
        print(f"  Evidence created: {result.evidence_created}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
