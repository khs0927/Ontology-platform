import argparse
import json
import sys
from pathlib import Path

import ezdxf
from pydantic import ValidationError

from god_cad.models import Drawing, Patch, PlanReport
from god_cad.pipeline import analyze
from god_cad.planner import dry_run


def write_new(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse all overwrites, including accidentally pointing at the source drawing.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="god-cad")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Analyze top-level modelspace entities in a DXF")
    ingest.add_argument("source", type=Path)
    ingest.add_argument("--drawing-id", required=True, help="Stable caller-managed logical ID")
    ingest.add_argument("--units", choices=["mm", "cm", "m", "in", "ft"])
    ingest.add_argument("--out", type=Path, required=True)
    plan = commands.add_parser("plan", help="Simulate a structured patch; never writes CAD files")
    plan.add_argument("drawing", type=Path)
    plan.add_argument("patch", type=Path)
    plan.add_argument("--out", type=Path, required=True)
    render = commands.add_parser("render", help="Generate an ezdxf SVG preview")
    render.add_argument("source", type=Path)
    render.add_argument("--out", type=Path, required=True)
    schema = commands.add_parser("schema", help="Export a versioned JSON Schema")
    schema.add_argument("kind", choices=["drawing", "patch", "report"])
    schema.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            result = analyze(args.source, args.drawing_id, args.units)
            write_new(args.out, result.model_dump_json(indent=2))
            print(f"{len(result.entities)} entities, {len(result.warnings)} warnings -> {args.out}")
        elif args.command == "plan":
            drawing = Drawing.model_validate_json(args.drawing.read_text(encoding="utf-8"))
            patch = Patch.model_validate_json(args.patch.read_text(encoding="utf-8"))
            report = dry_run(drawing, patch)
            write_new(args.out, report.model_dump_json(indent=2))
            print(f"{report.status}; native_write_eligible=false -> {args.out}")
            return 2 if report.errors else 0
        elif args.command == "render":
            from god_cad.render import render_svg

            write_new(args.out, render_svg(args.source))
            print(f"DXF preview only -> {args.out}")
        else:
            contract = {"drawing": Drawing, "patch": Patch, "report": PlanReport}[args.kind]
            write_new(args.out, json.dumps(contract.model_json_schema(), indent=2))
    except (OSError, ValueError, ValidationError, ezdxf.DXFError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
