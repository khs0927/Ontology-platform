"""``sion-relations``: convert graph exports, import them, extract candidate relations.

Examples::

    sion-relations convert page.html -o export.json --expect-nodes 31 --expect-edges 43
    sion-relations import export-or-page.json --database-url sqlite:///runtime/sion.db
    sion-relations extract docs/*.md drawings/*.dxf --database-url postgresql+psycopg://...
    sion-relations candidates --database-url ... [--status pending]

All imported/extracted relations are unverified candidates unless ``--verified``
is passed to ``import`` (use only for an export a human already reviewed).
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _session(database_url: str):
    """Session for one CLI command. When a storage root is configured (``SION_STORAGE_ROOT`` /
    ``SION_DRIVE_ROOT``), a command that wrote anything ends with one Drive export."""
    from sion_api import repository
    from sion_api.db import Base, build_engine, build_session_factory
    from sion_api.drive_export import DriveExporter, install_export_on_write

    engine = build_engine(database_url)
    if database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    exporter = DriveExporter.from_env(engine)
    if exporter is not None:
        exporter.debounce_s = 3600.0  # export once at the end, not in the middle of an import
        install_export_on_write(factory, exporter)
    with factory() as session:
        repository.seed_core_types(session)
        yield session
    if exporter is not None:
        exporter.flush()
        if exporter.last_result:
            print(f"[drive] exported to {exporter.layout.root}", file=sys.stderr)


def _inventory(path: str | None) -> dict | None:
    if not path:
        default = Path(__file__).resolve().parents[3] / "data" / "bootstrap" / "current-map-inventory.json"
        path = str(default) if default.exists() else None
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sion-relations", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def export_args(p):
        p.add_argument("path")
        p.add_argument("--namespace")
        p.add_argument("--expect-nodes", type=int)
        p.add_argument("--expect-edges", type=int)
        p.add_argument("--graph-index", type=int)
        p.add_argument("--allow-implicit-nodes", action="store_true")
        p.add_argument("--verified", action="store_true", help="mark edges human_verified (already reviewed export)")
        p.add_argument("--inventory", help="sion-map-inventory/v1 file to compare labels/counts against")

    convert = sub.add_parser("convert", help="convert a graph export to sion-map-export/v1")
    export_args(convert)
    convert.add_argument("-o", "--output")

    imp = sub.add_parser("import", help="convert (if needed) and import into a database")
    export_args(imp)
    imp.add_argument("--database-url", required=True)

    extract = sub.add_parser("extract", help="propose candidate relations from documents/DXF/IFC")
    extract.add_argument("paths", nargs="+")
    extract.add_argument("--database-url", required=True)
    extract.add_argument("--min-cooccurrence", type=int, default=2)
    extract.add_argument("--no-cooccurrence", action="store_true")

    cand = sub.add_parser("candidates", help="list candidate relations")
    cand.add_argument("--database-url", required=True)
    cand.add_argument("--status", default="pending", choices=["pending", "approved", "rejected", "all"])
    cand.add_argument("--limit", type=int, default=100)

    args = parser.parse_args(argv)

    if args.command in {"convert", "import"}:
        from sion_ingestion.graph_export import (
            GraphExportError,
            attach_export_evidence,
            compare_with_inventory,
            convert_file,
        )

        try:
            export, report = convert_file(
                args.path,
                namespace=args.namespace,
                expected_nodes=args.expect_nodes,
                expected_edges=args.expect_edges,
                as_candidates=not args.verified,
                graph_index=args.graph_index,
                allow_implicit_nodes=args.allow_implicit_nodes,
            )
        except GraphExportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        summary = {"report": report.as_dict()}
        inventory = _inventory(args.inventory)
        if inventory:
            summary["inventory"] = compare_with_inventory(export, inventory)
        if args.command == "convert":
            text = json.dumps(export.model_dump(by_alias=True), ensure_ascii=False, indent=2) + "\n"
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
            print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
            return 0
        from sion_ingestion.map_import import import_map_export

        with _session(args.database_url) as session:
            summary["import"] = import_map_export(session, export).model_dump()
            uri = Path(args.path).resolve().as_uri()
            summary["evidence_created"] = attach_export_evidence(session, export, source_uri=uri)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "extract":
        from sion_ingestion.relation_extraction import extract_relation_candidates

        with _session(args.database_url) as session:
            result = extract_relation_candidates(
                session,
                [Path(p) for p in args.paths],
                min_cooccurrence=args.min_cooccurrence,
                include_cooccurrence=not args.no_cooccurrence,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    from sion_api import review

    with _session(args.database_url) as session:
        print(json.dumps(review.list_candidates(session, status=args.status, limit=args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
