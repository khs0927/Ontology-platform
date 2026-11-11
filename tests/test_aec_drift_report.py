"""Offline regression tests for the AEC read-only drift inventory."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "aec_drift_report.py"
_SPEC = importlib.util.spec_from_file_location("aec_drift_report", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
compare = _MODULE.compare
inventory = _MODULE.inventory


class DriftInventoryTest(unittest.TestCase):
    def test_identical_modified_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / "upstream", root / "bundled"
            for side in (old, new):
                (side / "src").mkdir(parents=True)
            (old / "src" / "same.py").write_text("match", encoding="utf-8")
            (new / "src" / "same.py").write_text("match", encoding="utf-8")
            (old / "src" / "changed.py").write_text("original", encoding="utf-8")
            (new / "src" / "changed.py").write_text("updated", encoding="utf-8")
            (old / "src" / "legacy.py").write_text("upstream", encoding="utf-8")
            (new / "src" / "local.py").write_text("local", encoding="utf-8")
            report = compare(inventory(old), inventory(new))
            self.assertEqual(report["counts"], {
                "identical": 1, "modified": 1, "upstream_only": 1, "bundled_only": 1,
            })
            self.assertEqual(
                [(row["path"], row["state"]) for row in report["files"]],
                [
                    ("src/changed.py", "modified"),
                    ("src/legacy.py", "upstream_only"),
                    ("src/local.py", "bundled_only"),
                    ("src/same.py", "identical"),
                ],
            )
            self.assertFalse(report["safe_to_apply_automatically"])

    def test_ignores_binary_and_generated_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests" / "__pycache__").mkdir(parents=True)
            (root / "tests" / "__pycache__" / "bad.py").write_text("ignored")
            (root / "tests" / "binary.dwg").write_bytes(b"ignored")
            (root / "tests" / ".secret.py").write_text("ignored")
            (root / "tests" / "visible.py").write_text("valid")
            self.assertEqual(list(inventory(root)), ["tests/visible.py"])

    def test_requires_existing_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                inventory(Path(directory) / "missing")


if __name__ == "__main__":
    unittest.main()
