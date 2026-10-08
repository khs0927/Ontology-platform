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
