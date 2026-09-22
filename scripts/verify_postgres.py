#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

from sqlalchemy import create_engine, text


REQUIRED_TABLES = (
    "ontology_versions",
    "entity_types",
    "relation_types",
    "entities",
    "artifacts",
    "documents",
    "chunks",
    "relations",
    "evidence",
    "embeddings",
)


def main() -> int:
    url = os.getenv("ONTOLOGY_DATABASE_URL")
    if not url:
        print("ONTOLOGY_DATABASE_URL is required.", file=sys.stderr)
        return 2
    if not url.startswith("postgresql"):
        print("ONTOLOGY_DATABASE_URL must point to PostgreSQL.", file=sys.stderr)
        return 2

    engine = create_engine(url, future=True)
    report: dict[str, object] = {
        "database": "postgresql",
        "connection": False,
        "extensions": {},
        "tables": {},
        "seed_counts": {},
    }

    with engine.connect() as conn:
        report["connection"] = conn.execute(text("SELECT 1")).scalar_one() == 1
        report["server_version"] = conn.execute(text("SHOW server_version")).scalar_one()

        extension_rows = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto', 'vector') ORDER BY extname")
        ).scalars()
        found_extensions = set(extension_rows)
        report["extensions"] = {
            "pgcrypto": "pgcrypto" in found_extensions,
            "vector": "vector" in found_extensions,
        }

        table_status: dict[str, bool] = {}
        for table in REQUIRED_TABLES:
            table_status[table] = conn.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            ).scalar_one()
        report["tables"] = table_status

        if table_status["entity_types"]:
            report["seed_counts"]["entity_types"] = conn.execute(text("SELECT count(*) FROM entity_types")).scalar_one()
        if table_status["relation_types"]:
            report["seed_counts"]["relation_types"] = conn.execute(text("SELECT count(*) FROM relation_types")).scalar_one()

    print(json.dumps(report, ensure_ascii=False, indent=2))

    extensions_ok = all(report["extensions"].values())
    tables_ok = all(report["tables"].values())
    return 0 if report["connection"] and extensions_ok and tables_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
