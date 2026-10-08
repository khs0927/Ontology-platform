from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("public_privacy", Path(__file__).parents[1] / "scripts/check_public_privacy.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_private_values_are_identified_without_returning_them():
    email = b"fixture-person" + b"@" + b"gmail.com"
    path = b"C:" + b"\\Users\\" + b"fixture-person\\file.txt"
    folder = b"https://drive.google.com/drive/folders/" + b"1" + b"X" * 30
    assert checker.violations(email) == ["personal email"]
    assert checker.violations(path) == ["personal profile path"]
    assert checker.violations(folder) == ["private Drive identifier"]


def test_generic_examples_and_public_commit_identifiers_are_allowed():
    assert checker.violations(b"C:\\Users\\USER\\project") == []
    assert checker.violations(b"private@example.invalid") == []
    assert checker.violations(b"drive revision `1" + b"a" * 39 + b"`") == []
