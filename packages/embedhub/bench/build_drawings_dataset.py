"""Build a retrieval benchmark from the repo's Korean DXF fixtures.

    python packages/embedhub/bench/build_drawings_dataset.py OUT_DIR
    python -m sion_embedhub.cli bench-drawings OUT_DIR

The second command renders this same corpus and scores it. Renders stay in OUT_DIR.

Writes OUT_DIR/renders/<id>.png (matplotlib render of each sheet), OUT_DIR/drawings.jsonl (one doc per
sheet carrying both its extracted text and its rendered image) and appends the hand-labelled queries from
drawing_queries.jsonl. Renders are generated, never committed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[2] / "packages" / "aec" / "tests" / "fixtures" / "drawings_ko"


def sheet_id(path: Path) -> str:
    return re.match(r"[A-Z]-\d+", path.stem).group(0)


def sheet_text(doc) -> str:
    parts = []
    for e in doc.modelspace():
        if e.dxftype() == "TEXT":
            parts.append(e.dxf.text)
        elif e.dxftype() == "MTEXT":
            parts.append(e.plain_text())
    return "\n".join(p.strip() for p in parts if p and p.strip())


def render(doc, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    for font in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"):
        try:
            matplotlib.font_manager.findfont(font, fallback_to_default=False)
            plt.rcParams["font.family"] = font
            break
        except ValueError:
            continue
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration

    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
    fig = plt.figure(figsize=(12, 8.5), dpi=130)
    ax = fig.add_axes([0, 0, 1, 1])
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    fig.savefig(out, facecolor="white")
    plt.close(fig)


def main(out_dir: str) -> int:
    import ezdxf

    out = Path(out_dir)
    (out / "renders").mkdir(parents=True, exist_ok=True)
    lines = []
    for path in sorted(FIXTURES.glob("*.dxf")):
        doc = ezdxf.readfile(path)
        sid = sheet_id(path)
        png = out / "renders" / f"{sid}.png"
        render(doc, png)
        text = f"{path.stem}\n{sheet_text(doc)}"
        lines.append(json.dumps({"type": "doc", "id": sid, "text": text, "image": f"renders/{sid}.png"}, ensure_ascii=False))
    lines.extend((HERE / "drawing_queries.jsonl").read_text(encoding="utf-8").splitlines())
    (out / "drawings.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines)} lines -> {out / 'drawings.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
