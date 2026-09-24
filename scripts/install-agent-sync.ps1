# Automated Background Sync Task Installer for Windows
# Registers a least-privilege, current-user task without deleting an existing task.
param(
    [ValidateRange(1, 1440)][int]$IntervalMinutes = 15,
    [ValidateNotNullOrEmpty()][string]$TaskName = "SionAgentOntologySync"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir
$bridgeScript = Join-Path $scriptDir "run_agent_bridge.py"
$pythonExe = (Get-Command python.exe -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $bridgeScript -PathType Leaf)) { throw "Bridge script not found: $bridgeScript" }

# Never unregister a colliding task: it may belong to another worker or install.
$taskPath = "\"
$marker = "SionAgentOntologySync:v2"
$existing = @(Get-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) { throw "Scheduled task '$taskPath$TaskName' already exists; refusing to modify or delete it." }
$markerCollision = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like "*$marker*" -or $_.Description -like "*$marker*" })
if ($markerCollision.Count -gt 0) { throw "Scheduled task marker '$marker' is already in use; refusing to modify existing tasks." }

# Direct executable and argument array, never a shell command string.
$actionArgs = [string[]]@($bridgeScript)
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $actionArgs -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Managed by $marker"
Register-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -InputObject $task -ErrorAction Stop | Out-Null
Write-Host "[+] Successfully registered Scheduled Task '$taskPath$TaskName'."

Write-Host "[*] Running initial sync test..."
& $pythonExe $bridgeScript
$initialExit = $LASTEXITCODE
if ($initialExit -ne 0) { throw "Initial sync failed with exit code $initialExit" }
Write-Host "[+] All set! This computer will now automatically ingest and sync agent sessions."
