"""Compatibility alias: moved to ``sion_bim.ifc``. Import from there in new code."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("sion_bim.ifc")
