# Automated Background Sync Task Installer for Windows
# Registers a scheduled task that runs every 15 minutes in the background.

param(
    [string]$IntervalMinutes = "15",
    [string]$TaskName = "SionAgentOntologySync"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir
$pythonExe = (Get-Command python).Source
$bridgeScript = Join-Path $scriptDir "run_agent_bridge.py"

Write-Host "[*] Configuring automated ontology sync task: $TaskName"
Write-Host "    - Python: $pythonExe"
Write-Host "    - Script: $bridgeScript"
Write-Host "    - Interval: Every $IntervalMinutes minutes"

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$bridgeScript`"" -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes ([int]$IntervalMinutes))
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Automated multi-agent ontology session ingestion and Google Drive sync"
    Write-Host "[+] Successfully registered Scheduled Task '$TaskName'."
} catch {
    # Fallback to schtasks if New-ScheduledTask fails
    $schCmd = "schtasks /Create /F /SC MINUTE /MO $IntervalMinutes /TN `"$TaskName`" /TR `"`"$pythonExe`" `"$bridgeScript`"`""
    Invoke-Expression $schCmd
    Write-Host "[+] Successfully registered task using schtasks."
}

Write-Host "[*] Running initial sync test..."
& $pythonExe $bridgeScript
Write-Host "[+] All set! This computer will now automatically ingest and sync agent sessions."
