"""Optional-dependency registry and lazy import helpers.

Heavy libraries (ezdxf, ifcopenshell, LightRAG, Google API client, ...) are
installed through extras of ``sion-ontology-platform`` and must only be
imported inside the function that needs them. Use :func:`require` there so the
error tells the operator which extra to install, and :func:`extras_report` to
show what is available without importing anything heavy.
"""

from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

DIST = "sion-ontology-platform"

# extra name -> import names that prove the extra is installed
EXTRAS: dict[str, tuple[str, ...]] = {
    "cad": ("ezdxf",),
    "bim": ("ifcopenshell",),
    "rag": ("lightrag", "asyncpg", "pgvector"),
    "drive": ("googleapiclient", "google.oauth2"),
    "regulation": ("pydantic_settings", "asyncpg", "greenlet"),
}

# import name -> extra that provides it
_MODULE_TO_EXTRA = {module: extra for extra, modules in EXTRAS.items() for module in modules}


class MissingExtra(ImportError):
    """Raised when an optional dependency is required but not installed."""

    def __init__(self, module: str, extra: str | None):
        self.module = module
        self.extra = extra
        hint = f" Install it with: pip install '{DIST}[{extra}]'" if extra else ""
        super().__init__(f"optional dependency '{module}' is not installed.{hint}")


def is_available(module: str) -> bool:
    """True when ``module`` can be imported. Does not import it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def require(module: str, extra: str | None = None) -> ModuleType:
    """Import ``module`` lazily or raise :class:`MissingExtra` naming the extra."""
    extra = extra or _MODULE_TO_EXTRA.get(module.split(".")[0]) or _MODULE_TO_EXTRA.get(module)
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingExtra(module, extra) from exc


def extras_report() -> dict[str, dict[str, object]]:
    """Which extras are installed, computed with ``find_spec`` only (no heavy imports)."""
    report: dict[str, dict[str, object]] = {}
    for extra, modules in EXTRAS.items():
        missing = [module for module in modules if not is_available(module)]
        report[extra] = {"installed": not missing, "modules": list(modules), "missing": missing}
    return report
