"""Fail-closed signing policy: only Authenticode ``Valid`` is a release candidate.

``NotTrusted``, ``NotSigned``, ``UnknownError``, ``Unavailable`` and
``HashMismatch`` must all block the release.
"""

import json
import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "preflight-signing.ps1"
BLOCKED_STATUSES = ("NotSigned", "NotTrusted", "UnknownError", "Unavailable", "HashMismatch")


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def _run_preflight(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("POWERSHELL", "pwsh")
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-RepoRoot", str(repo)],
        capture_output=True, text=True, env=env,
    )


def test_nottrusted_is_no_longer_treated_as_signed():
    text = _script_text()
    assert "'Valid', 'NotTrusted'" not in text
    assert "Valid'," not in text.replace("$SignedStatus = 'Valid'", "")
    signed_lines = [ln.strip() for ln in text.splitlines() if "$signed" in ln and "-in" in ln]
    assert len(signed_lines) == 1, signed_lines
    assert re.fullmatch(r"\$signed\s*=\s*\$authenticodeStatus\s+-in\s+@\('Valid'\)", signed_lines[0])
    # NotTrusted must still be named, as an explicitly blocked state.
    assert "NotTrusted" in text
    for status in BLOCKED_STATUSES:
        assert status in text


def test_policy_blocked_statuses_cover_every_non_valid_state():
    text = _script_text()
    match = re.search(r"\$BlockedStatuses\s*=\s*@\(([^)]*)\)", text)
    assert match, "BlockedStatuses allow-list of fail-closed states is missing"
    listed = set(re.findall(r"'([^']+)'", match.group(1)))
    assert listed == set(BLOCKED_STATUSES)


def test_script_stays_detect_only_and_read_only():
    text = _script_text().lower()
    assert "set-authenticodesignature" not in text
    assert "get-authenticodesignature" in text
    assert "sign " not in text.replace("signing ", "")
    assert "detect_only" in text
    assert "exit 2" in text


def test_unsigned_artifact_blocks_with_valid_only_policy(tmp_path):
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "dist").mkdir()
    (repo / "bin" / "tool.exe").write_bytes(b"not signed")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "bin/tool.exe"], check=True)

    result = _run_preflight(repo)
    assert result.returncode == 2, result.stderr

    report = json.loads(
        (repo / "tmp" / "signing-preflight" / "signing-preflight.json").read_text(encoding="utf-8-sig")
    )
    assert report["read_only"] is True
    assert report["detect_only"] is True
    assert report["signing_policy"]["accepted_statuses"] == ["Valid"]
    assert report["signing_policy"]["fail_closed"] is True
    assert set(report["signing_policy"]["blocked_statuses"]) == set(BLOCKED_STATUSES)

    artifact = report["artifacts"][0]
    assert artifact["signed"] is False
    assert artifact["trusted"] is False
    assert artifact["blocked"] is True
    assert artifact["authenticode_status"] != "Valid"

    block = report["unsigned_release_block"]
    assert block["blocked"] is True
    assert block["artifact_count"] == 1
    assert block["blocked_artifacts"]
    assert artifact["block_reason"]


def test_no_release_candidates_also_blocks(tmp_path):
    repo = tmp_path / "empty"
    (repo / "bin").mkdir(parents=True)
    (repo / "dist").mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)

    result = _run_preflight(repo)
    assert result.returncode == 2, result.stderr
    report = json.loads(
        (repo / "tmp" / "signing-preflight" / "signing-preflight.json").read_text(encoding="utf-8-sig")
    )
    assert report["artifacts"] == []
    assert report["unsigned_release_block"]["blocked"] is True
