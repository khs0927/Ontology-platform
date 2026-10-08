"""Static checks for scripts/ops/switch-to-monorepo.ps1 (the PC itself is not available in CI)."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "switch-to-monorepo.ps1"
RUNBOOK = Path(__file__).resolve().parents[1] / "docs" / "SWITCH-TO-MONOREPO.ko.md"
SHELL = shutil.which("pwsh") or shutil.which("powershell")
MUTATING = (
    "Unregister-ScheduledTask", "Disable-ScheduledTask", "Enable-ScheduledTask", "Start-ScheduledTask",
    "Stop-ScheduledTask", "Register-ScheduledTask", "Copy-Item", "Rename-Item", "Remove-Item",
    "Set-DotEnvValue", "Invoke-OpsScript", "Set-Content",
)

# Parse with the real PowerShell parser; report errors and every mutating command that is not guarded
# by Invoke-Change { ... }, `if (-not $DryRun)` or a function that returns early in dry-run mode.
PARSE = r'''
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:SWITCH_SCRIPT, [ref]$tokens, [ref]$errors)
$mut = $env:SWITCH_MUTATING -split ','
$unguarded = @()
foreach ($cmd in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)) {
    $name = $cmd.GetCommandName()
    if ($mut -notcontains $name) { continue }
    $guarded = $false
    $p = $cmd.Parent
    while ($p) {
        if ($p -is [System.Management.Automation.Language.ScriptBlockExpressionAst] -and
            $p.Parent -is [System.Management.Automation.Language.CommandAst] -and
            $p.Parent.GetCommandName() -eq 'Invoke-Change') { $guarded = $true; break }
        if ($p -is [System.Management.Automation.Language.IfStatementAst] -and
            $p.Clauses[0].Item1.Extent.Text -match '-not \$DryRun') { $guarded = $true; break }
        if ($p -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            ($p.Body.Extent.Text -match 'if \(\$DryRun\) \{[^}]*return' -or $p.Name -in @('Set-DotEnvValue', 'Invoke-OpsScript'))) {
            $guarded = $true; break
        }
        $p = $p.Parent
    }
    if (-not $guarded) { $unguarded += "$name@$($cmd.Extent.StartLineNumber)" }
}
[pscustomobject]@{ errors = @($errors | ForEach-Object { $_.ToString() }); unguarded = $unguarded } | ConvertTo-Json -Compress
'''


@pytest.mark.skipif(not SHELL, reason="PowerShell is required to parse the ops script")
def test_script_parses_and_every_change_is_dry_run_guarded():
    import os

    env = dict(os.environ, SWITCH_SCRIPT=str(SCRIPT), SWITCH_MUTATING=",".join(MUTATING))
    out = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-Command", PARSE], env=env,
                         capture_output=True, text=True, timeout=120, check=True).stdout
    result = json.loads(out.strip().splitlines()[-1])
    assert result["errors"] in ([], None)
    assert result["unguarded"] in ([], None), result["unguarded"]


def test_script_is_dry_run_by_default_and_reuses_ops_scripts():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$DryRun = -not $Apply" in text
    for needed in ("stop-workers.ps1", "register-host-tasks.ps1", "register-bulk-tasks.ps1", "-Drain", "-Resume",
                   "Export-ScheduledTask", "AutoSync_Code_To_GDrive", "COMPOSE_PROJECT_NAME", "_aec-pgdata",
                   "/healthz", "/v1/kg/stats", "AEC-GraphRAG-Refresh", "AEC-Ops-FinalWrap", "AEC-Ops-FinalCheck"):
        assert needed in text, needed
    # The token is read into a variable for the Authorization header and never written to the log.
    assert not re.search(r"Write-(Log|Host)[^\n]*\$token", text)


@pytest.mark.parametrize("path", [SCRIPT, RUNBOOK])
def test_no_personal_paths(path):
    text = path.read_text(encoding="utf-8")
    profile = [m for m in re.findall(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'`]+)", text, re.I)
               if m.lower() not in {"user", "username", "public", "<user>", "<username>"}]
    assert profile == []
    assert not re.search(r"[A-Za-z0-9._%+-]+@(gmail|naver|hanmail|daum|hotmail|outlook)\.", text, re.I)


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start): text.index(end)]


def test_python_312_is_enforced_in_preflight_before_any_change():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$MinPython = [version]'3.12'" in text
    preflight = _section(text, "# --- 1. preflight", "# --- 2. inventory")
    # resolved and version-checked before the drain/disable steps; explicit -Python must also satisfy it
    assert "Get-PythonVersion $Python" in preflight and "-lt $MinPython" in preflight
    assert "-ge $MinPython" in preflight and "throw \"no Python >= $MinPython found" in preflight
    venv = _section(text, "# --- 8. host venv", "# --- 9. scheduled tasks")
    assert "pyvenv.cfg" not in venv  # no un-checked legacy interpreter fallback at venv time


def test_legacy_targeting_tasks_are_never_re_enabled():
    text = SCRIPT.read_text(encoding="utf-8")
    loop = _section(text, "if (-not $DryRun) {\n    foreach ($t in (Get-AecTasks))", "# --- 10. AutoSync")
    legacy_branch = loop[loop.index('if ($a -like "*$LegacyRoot*")'): loop.index("if ($t.State -eq 'Disabled')")]
    assert "Disable-ScheduledTask" in legacy_branch and "continue" in legacy_branch
    assert "Enable-ScheduledTask" not in legacy_branch


@pytest.mark.parametrize("path", ["packages/aec/.venv.old-20260101-000000/pyvenv.cfg",
                                  "packages/aec/docker-compose.override.yml"])
def test_switch_side_files_are_git_ignored_so_retries_pass_the_clean_tree_check(path):
    git = shutil.which("git")
    root = Path(__file__).resolve().parents[3]
    if not git or not (root / ".git").exists():
        pytest.skip("needs a git checkout of the monorepo")
    result = subprocess.run([git, "-C", str(root), "check-ignore", "-q", "--no-index", path], capture_output=True)
    assert result.returncode == 0, f"{path} would dirty the worktree"


def test_docker_templates_survive_windows_powershell_quote_stripping():
    # Live PS 5.1 dry-run: '{{ index .Config.Labels "com.docker.compose.project" }}' lost its inner quotes
    # ("function com not defined"), so the project/volume checks were silently skipped.
    text = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    templates = re.findall(r"--format',?\s*'([^']*)'|--format\s+'([^']*)'", code)
    templates = [a or b for a, b in templates]
    assert templates and all('"' not in t for t in templates), templates
    assert "{{json .Config.Labels}}" in code and "{{json .Mounts}}" in code
    assert "com.docker.compose.project" in code and "ConvertFrom-Json" in code
    # the post-switch volume check uses the same parser
    stack = _section(text, "# --- 7. docker stack", "# --- 8. host venv")
    assert "(Get-AecDbInfo).Volume" in stack and "docker inspect" not in stack


def test_health_url_follows_aec_api_host_port():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "[string]$ApiUrl = ''," in text
    assert "Get-DotEnvValue $LegacyEnv 'AEC_API_HOST_PORT'" in text and "$apiPort = 58000" in text


def test_compose_project_inference_order():
    text = SCRIPT.read_text(encoding="utf-8")
    section = _section(text, "# --- 3. compose project / volume", "# --- 4. backups")
    order = ["'-ComposeProject'", "COMPOSE_PROJECT_NAME'", "'aec-db compose label'", "aec-db volume $dbVolume",
             "only existing volume", "legacy folder name (compose default)"]
    positions = [section.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "several *_aec-pgdata volumes exist" in section and "ConvertTo-ComposeProjectName" in section
