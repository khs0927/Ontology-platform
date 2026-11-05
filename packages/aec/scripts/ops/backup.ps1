<#
.SYNOPSIS
  pg_dump (custom format) of the aec database into a local backups folder, keeping the newest N dumps,
  then copies the kept dumps to a mirror folder (Google Drive). The dump runs inside the container
  (pg_dump -f + docker cp). If the mirror is not mounted the copy is reported as pending and retried
  on the next run; the local dump is never lost because Drive is offline.
  Only files named aec-db-YYYYMMDDTHHMMSSZ.dump in those folders are ever rotated/deleted.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\ops\backup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\ops\backup.ps1 -Target 'D:\AECData\backups' -Keep 30
  powershell -ExecutionPolicy Bypass -File scripts\ops\backup.ps1 -NoMirror
#>
param(
    [string]$Target = '',
    [int]$Keep = 14,
    [string]$Container = 'aec-db',
    [string]$Mirror = '',
    [switch]$NoMirror,
    [switch]$UseLocalPgDump
)
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not $Target) {
    $Target = if ($env:AEC_BACKUP_DIR) { $env:AEC_BACKUP_DIR } else { 'D:\AECData\backups' }
}
if (-not $Mirror -and -not $NoMirror) {
    $Mirror = if ($env:AEC_BACKUP_MIRROR) { $env:AEC_BACKUP_MIRROR } else { 'G:\내 드라이브\AEC-INTELLIGENCE\backups' }
}
$logDir = Join-Path $script:RepoRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ('backup-' + (Get-Date -Format 'yyyyMMdd') + '.log')

$cliArgs = @('backup', '--target', $Target, '--keep', "$Keep")
if (-not $UseLocalPgDump) { $cliArgs += @('--docker-container', $Container) }
if ($Mirror -and -not $NoMirror -and ($Mirror -ne $Target)) { $cliArgs += @('--mirror', $Mirror) }
try {
    $out = Invoke-AecCli -Arguments $cliArgs 2>&1 | Tee-Object -FilePath $log -Append
    $out
    Write-Host "Backup OK -> $Target"
    if (($out | Out-String) -match '"status":\s*"pending"') {
        "[$(Get-Date -Format s)] WARN mirror pending (not mounted?): $Mirror - retried on next run" | Tee-Object -FilePath $log -Append
    }
} catch {
    "[$(Get-Date -Format s)] BACKUP FAILED: $_" | Tee-Object -FilePath $log -Append
    exit 1
}
