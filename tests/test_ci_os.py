"""Lock the OS split for pytest so a full Windows suite is not assumed to exist."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_full_pytest_jobs_are_ubuntu_only():
    tests = _text("tests.yml")
    verify = _text("verify.yml")
    assert "windows-latest" not in tests
    assert "runs-on: ubuntu-latest" in tests
    assert "python -m pytest" in tests
    assert "windows-latest" not in verify
    assert "python -m pytest -q" in verify


def test_windows_pytest_is_god_cad_only():
    aec = _text("aec.yml")
    assert "windows-latest" in aec
    assert "working-directory: packages/cad/god-cad" in aec
    assert "python -m pytest -q" in aec
