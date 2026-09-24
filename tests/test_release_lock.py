from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-release-lock.py"
spec = importlib.util.spec_from_file_location("release_lock", SCRIPT)
assert spec and spec.loader
lock_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lock_mod)


def test_repository_lock_is_exact_and_hash_pinned() -> None:
    lock_mod.verify()
    entries = lock_mod.parse_lock(ROOT / "requirements-release.lock")
    assert ("httpx2", "") in entries
    assert ("pyyaml", "") in entries
    assert ("pgvector", "") in entries
    assert ("pyinstaller", "") in entries
    assert ("setuptools", "") in entries
    assert all(len(digest) == 71 and digest.startswith("sha256:") for _, digest in entries.values())


def test_verifier_fails_closed_on_drift_missing_extra_and_unhashed(tmp_path: Path) -> None:
    original = (ROOT / "requirements-release.lock").read_text(encoding="utf-8")
    mutated = original.replace("httpx2==2.13.1", "httpx2==2.13.0")
    (ROOT / "requirements-release.lock").write_text(mutated, encoding="utf-8")
    try:
        lock_mod.verify()
    except SystemExit as exc:
        assert "drift" in str(exc)
    else:
        raise AssertionError("version drift was accepted")
    (ROOT / "requirements-release.lock").write_text(original, encoding="utf-8")


def test_verifier_script_exits_zero() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
