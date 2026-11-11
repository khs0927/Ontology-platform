"""Run the real task-registration scripts with the ScheduledTasks cmdlets mocked.

Guards the runtime tasks that used to exist only on the main PC's archived checkout
(AEC-Bulk-Observe, AEC-Docker-Startup) so a re-registration from packages/aec keeps them, and
the repetition watchdogs that must not stop a live task at the 1-day repetition boundary.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

OPS = Path(__file__).resolve().parents[1] / "scripts" / "ops"
SHELL = shutil.which("pwsh") or shutil.which("powershell")
needs_shell = pytest.mark.skipif(not SHELL, reason="PowerShell is required for the ops registration test")

MOCKS = r'''
$global:Registered = New-Object System.Collections.Generic.List[object]
function global:New-TimeSpan { param([int]$Days = 0, [int]$Hours = 0, [int]$Minutes = 0)
    [TimeSpan]::new($Days, $Hours, $Minutes, 0) }
function global:New-ScheduledTaskTrigger {
    param([switch]$Daily, [switch]$Once, [switch]$AtLogOn, $At, $User, $RepetitionInterval, $RepetitionDuration)
    $kind = if ($AtLogOn) { 'logon' } elseif ($Daily) { 'daily' } else { 'once' }
    $rep = [pscustomobject]@{ Interval = $(if ($RepetitionInterval) { $RepetitionInterval.TotalMinutes } else { $null });
                              StopAtDurationEnd = $true }
    [pscustomobject]@{ Kind = $kind; At = "$At"; Repetition = $rep; Delay = $null }
}
function global:New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory)
    [pscustomobject]@{ Execute = $Execute; Argument = $Argument } }
function global:New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) [pscustomobject]@{ UserId = $UserId } }
function global:New-ScheduledTaskSettingsSet {
    param([switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, [switch]$StartWhenAvailable,
          $ExecutionTimeLimit, $MultipleInstances, $RestartCount, $RestartInterval, $Priority)
    [pscustomobject]@{ LimitMinutes = $ExecutionTimeLimit.TotalMinutes; MultipleInstances = "$MultipleInstances" } }
function global:Register-ScheduledTask { param($TaskPath, $TaskName, $Action, $Principal, $Settings, $Trigger, [switch]$Force)
    $global:Registered.Add([pscustomobject]@{
        name = $TaskName; path = $TaskPath; argument = $Action.Argument; settings = $Settings
        triggers = @($Trigger | ForEach-Object { [pscustomobject]@{ kind = $_.Kind; every = $_.Repetition.Interval;
                                                                    stop_at_end = $_.Repetition.StopAtDurationEnd } }) }) }
function global:Get-ScheduledTask { param($TaskPath, $TaskName) }
function global:Start-ScheduledTask { param($TaskPath, $TaskName) }
'''


def run_register(tmp_path, script, **params):
    out = tmp_path / "registered.json"
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(
        MOCKS
        + "\n$ErrorActionPreference = 'Stop'\n"
        + "$regArgs = @{" + "; ".join(f"{k} = '{v}'" for k, v in params.items()) + "}\n"
        + "try { & $env:REG_SCRIPT @regArgs | Out-Null } catch { Write-Error $_ -ErrorAction Continue; exit 1 }\n"
        + "$global:Registered | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $env:REG_OUT -Encoding UTF8\n",
        encoding="utf-8",
    )
    env = dict(os.environ, REG_SCRIPT=str(OPS / script), REG_OUT=str(out))
    env.setdefault("SystemRoot", str(tmp_path))  # the scripts resolve powershell.exe under it (Linux CI)
    result = subprocess.run([SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                            env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(out.read_text(encoding="utf-8-sig"))
    return {t["name"]: t for t in (data if isinstance(data, list) else [data])}


@needs_shell
def test_bulk_tasks_register_observe_and_keep_watchdog_alive(tmp_path):
    config = tmp_path / "bulk" / "sources.json"
    tasks = run_register(tmp_path, "register-bulk-tasks.ps1", Config=config, Workers=2)
    assert set(tasks) == {"AEC-Bulk-Workers", "AEC-Bulk-Census", "AEC-Bulk-Census-Refresh", "AEC-Bulk-Observe"}

    observe = tasks["AEC-Bulk-Observe"]
    assert "observe-bulk.ps1" in observe["argument"] and "-Once" in observe["argument"]
    assert str(config.parent / "logs" / "stability.jsonl") in observe["argument"]
    assert observe["settings"]["LimitMinutes"] == 2
    assert observe["settings"]["MultipleInstances"] == "IgnoreNew"
    [trigger] = observe["triggers"]
    assert trigger == {"kind": "daily", "every": 5, "stop_at_end": False}

    workers = tasks["AEC-Bulk-Workers"]
    repeating = [t for t in workers["triggers"] if t["every"]]
    assert repeating == [{"kind": "daily", "every": 10, "stop_at_end": False}]


@needs_shell
def test_host_tasks_register_docker_startup_at_logon_only(tmp_path):
    ollama_home = tmp_path / "Ollama"
    ollama_home.mkdir()
    (ollama_home / "ollama.exe").write_bytes(b"")
    tasks = run_register(tmp_path, "register-host-tasks.ps1", OllamaHome=ollama_home)
    assert set(tasks) == {"AEC-Ollama", "AEC-Reembed", "AEC-WSL-Reclaim", "AEC-GraphRAG-Refresh", "AEC-Docker-Startup"}

    docker = tasks["AEC-Docker-Startup"]
    assert "start-docker.ps1" in docker["argument"]
    assert docker["triggers"] == [{"kind": "logon", "every": None, "stop_at_end": True}]
    assert docker["settings"]["LimitMinutes"] == 2

    for name, task in tasks.items():
        for trigger in task["triggers"]:
            if trigger["every"]:
                assert trigger["stop_at_end"] is False, name

    only = run_register(tmp_path, "register-host-tasks.ps1", Only="DockerStartup")
    assert set(only) == {"AEC-Docker-Startup"}


def test_registered_scripts_exist_and_have_no_personal_paths():
    for name in ("observe-bulk.ps1", "start-docker.ps1", "register-bulk-tasks.ps1", "register-host-tasks.ps1"):
        text = (OPS / name).read_text(encoding="utf-8")
        assert "C:\\CODE\\Ontology" not in text
        assert "\\Users\\" not in text
