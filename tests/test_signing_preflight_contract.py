import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "preflight-signing.ps1"


def test_preflight_script_is_read_only_and_does_not_record_secret_identifiers():
    text = SCRIPT.read_text(encoding="utf-8-sig").lower()
    assert "set-authenticodesignature" not in text
    assert "get-authenticodesignature" in text
    assert "exit 2" in text
    for forbidden in ("subject", "serial", "thumbprint", "token"):
        assert f'"{forbidden}"' not in text.lower()


def test_preflight_writes_json_and_markdown_and_blocks_unsigned(tmp_path):
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "dist").mkdir()
    (repo / "bin" / "tool.exe").write_bytes(b"not signed")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "bin/tool.exe"], check=True)
    env = os.environ.copy()
    env["POWERSHELL"] = env.get("POWERSHELL", "pwsh")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-RepoRoot", str(repo)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 2, result.stderr
    out = repo / "tmp" / "signing-preflight"
    report = json.loads((out / "signing-preflight.json").read_text(encoding="utf-8-sig"))
    assert report["unsigned_release_block"]["blocked"] is True
    assert report["artifacts"][0]["size_bytes"] == 10
    assert len(report["artifacts"][0]["sha256"]) == 64
    assert (out / "signing-preflight.md").is_file()
