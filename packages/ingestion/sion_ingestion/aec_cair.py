"""Compatibility alias: moved to ``sion_cair.adapter``. Import from there in new code."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("sion_cair.adapter")
