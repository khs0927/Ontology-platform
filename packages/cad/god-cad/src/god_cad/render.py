"""An ezdxf preview, not independent evidence of DWG fidelity."""

from pathlib import Path

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, svg


def render_svg(path: Path) -> str:
    if path.suffix.lower() != ".dxf":
        raise ValueError("SVG preview accepts DXF only")
    document = ezdxf.readfile(path)
    backend = svg.SVGBackend()
    settings = config.Configuration(
        background_policy=config.BackgroundPolicy.WHITE,
        color_policy=config.ColorPolicy.BLACK,
    )
    Frontend(RenderContext(document), backend, config=settings).draw_layout(document.modelspace())
    return backend.get_string(layout.Page(210, 297, layout.Units.mm))
