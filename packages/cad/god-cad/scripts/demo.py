"""Build a synthetic DXF and exercise the read/plan/preview pipeline locally."""

import argparse
import hashlib
from pathlib import Path

import ezdxf

from god_cad.cli import write_new
from god_cad.models import Patch
from god_cad.pipeline import analyze
from god_cad.planner import dry_run
from god_cad.render import render_svg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("artifacts/demo"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    source = args.out / "synthetic.dxf"
    document = ezdxf.new("R2013", units=4)
    for layer in ["WAL1", "COL", "DOOR"]:
        document.layers.new(layer)
    modelspace = document.modelspace()
    corners = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
    for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
        modelspace.add_line(a, b, dxfattribs={"layer": "WAL1"})
    modelspace.add_circle((3000, 2000), 150, dxfattribs={"layer": "COL"})
    door = document.blocks.new("DEMO_DOOR")
    door.add_line((0, 0), (900, 0))
    door.add_arc((0, 0), 900, 0, 90)
    modelspace.add_blockref("DEMO_DOOR", (1000, 0), dxfattribs={"layer": "DOOR"})
    document.saveas(source)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    drawing = analyze(source, "demo-floor-001")
    write_new(args.out / "drawing.json", drawing.model_dump_json(indent=2))
    write_new(args.out / "preview.svg", render_svg(source))
    for name, cad_type in [("move-column", "CIRCLE"), ("move-one-wall-rejected", "LINE")]:
        target = next(e for e in drawing.entities if e.cad_type == cad_type)
        patch = Patch(
            patch_id=name,
            drawing_id=drawing.drawing_id,
            expected_revision=drawing.revision,
            operation="TRANSLATE_ENTITIES",
            target_ids=[target.id],
            vector_mm=(300, 0, 0),
            reason="Synthetic primitive translation demonstration; no semantic edit claim",
        )
        report = dry_run(drawing, patch)
        write_new(args.out / f"{name}.patch.json", patch.model_dump_json(indent=2))
        write_new(args.out / f"{name}.report.json", report.model_dump_json(indent=2))
        print(f"{name}: {report.status}; native_write_eligible={report.native_write_eligible}")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    print(f"{len(drawing.entities)} source entities; original DXF unchanged; output: {args.out}")


if __name__ == "__main__":
    main()
