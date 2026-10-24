"""Import a sion-map-export/v1 file into the Sion DB.

  python scripts/ontology/ingest_map.py runtime/ontology/zium_law_20261024.map.json --dsn postgresql+psycopg://...
DSN can also come from SION_DATABASE_URL / DATABASE_URL. Never pass secrets on the command line in shared logs.
"""
from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine
from sion_api.db import build_session_factory
from sion_ingestion.map_import import import_map_export, load_map_export


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dsn", default=os.environ.get("SION_DATABASE_URL") or os.environ.get("DATABASE_URL"))
    a = ap.parse_args()
    export = load_map_export(a.path)
    session = build_session_factory(create_engine(a.dsn))()
    with session.begin():
        r = import_map_export(session, export)
    print(json.dumps(r.model_dump()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
