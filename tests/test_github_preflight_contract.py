"""Contract tests for the read-only GitHub preflight script and documentation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preflight-github.ps1"
DOC = ROOT / "docs" / "GITHUB_PREFLIGHT.md"


def test_preflight_exists_and_declares_read_only_contract():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Run-ReadOnly 'git' @('remote','-v')" in text
    assert "Run-ReadOnly 'git' @('ls-remote'" in text
    assert "gh auth status" in text
    assert "branch_protection" in text
    assert "required_checks" in text
    assert "mutation_performed" in text
    assert "Redact" in text
    assert "authorization" in text.lower()
    assert "oauth" in text.lower()
    assert "[?&]" in text
    assert "REDACTED_EMAIL" in text


def test_gh_auth_report_is_minimal_and_redaction_is_synthetic_safe():
    text = SCRIPT.read_text(encoding="utf-8")
    auth_start = text.index("$ghStatus = Run-ReadOnly 'gh' @('auth','status')")
    auth_end = text.index("$ghRepo = Run-ReadOnly", auth_start)
    auth_block = text[auth_start:auth_end]
    assert "exit_code" in auth_block
    assert "authenticated" in auth_block
    assert "command =".lower() not in auth_block.lower()
    assert "output =".lower() not in auth_block.lower()
    assert "gh auth status" not in auth_block.split("Never persist", 1)[1]
    for fixture in (
        "Authorization: Bearer synthetic-secret",
        "token=synthetic-secret password=synthetic-secret",
        "oauth=synthetic-secret",
        "https://example.test/repo?access_token=synthetic-secret",
        "email=synthetic@example.test",
    ):
        assert "synthetic-secret" not in fixture or "REDACTED" in text


def test_preflight_contains_no_mutation_commands():
    text = SCRIPT.read_text(encoding="utf-8").lower()
    for command in ("git push", "gh pr create", "gh pr merge", "gh repo edit", "gh api --method patch"):
        assert command not in text


def test_documentation_explains_usage_and_safety():
    text = DOC.read_text(encoding="utf-8")
    assert "read-only" in text
    assert "preflight-github.ps1" in text
    assert "pytest" in text
    assert "redact" in text.lower()
