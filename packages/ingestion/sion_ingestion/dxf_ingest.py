"""Compatibility alias: moved to ``sion_cad.dxf``. Import from there in new code."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("sion_cad.dxf")
