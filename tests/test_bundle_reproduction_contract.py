from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bundle_reproduction_script_has_full_history_and_clean_room_gates() -> None:
    script = (ROOT / "scripts" / "reproduce-from-bundle.ps1").read_text(encoding="utf-8")

    assert "'-C', $verifyRepo, 'bundle', 'verify'" in script
    assert "'init', '--quiet', $verifyRepo" in script
    assert "'clone', '--no-local'" in script
    assert "'--depth'" not in script
    assert "'fetch', '--depth'" not in script
    assert "rev-parse --is-shallow-repository" in script
    assert "Cannot create a full-history bundle from a shallow repository" in script
    assert "Refusing to overwrite existing bundle" in script
    assert "New-FullHistoryBundle" in script
    assert "'bundle', 'create'" in script
    assert "artifacts" in script

    required = [
        "git", "clone", "rev-parse", "branch", "--show-current", "status", "--porcelain",
        "pip", "install", ".[test]", "pytest", "compileall", "pip", "check",
        "verify-release-lock.py", "build", "--wheel", "venv", "sion_api",
        "TestMode", "Fast", "Full", "715ea4c",
    ]
    assert all(item in script for item in required)
    assert "Docker" in script and "EXE" in script
    assert "Remove-Item" in script
    assert "git push" not in script and "git commit" not in script
