<#
.SYNOPSIS
  Start, stop or check the local Sion API (and the local embeddings endpoint) on Windows.

.DESCRIPTION
  Uses the user environment (SION_DATABASE_URL, SION_STORAGE_ROOT, SION_GRAPHRAG_*). The live DB
  must be on a local disk; assets and DB snapshots go to SION_STORAGE_ROOT (Google Drive).
  Runtime files (pids, logs) go to SION_RUNTIME_DIR (default %LOCALAPPDATA%\Sion).

  .\scripts\sion-local.ps1 start     # embeddings (if configured on 127.0.0.1) + API on SION_API_PORT (8010)
  .\scripts\sion-local.ps1 status
  .\scripts\sion-local.ps1 stop      # exports to the storage root first, then stops both
#>
param([ValidateSet('start', 'stop', 'status')][string]$Action = 'status')

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$runtime = if ($env:SION_RUNTIME_DIR) { $env:SION_RUNTIME_DIR } else { Join-Path $env:LOCALAPPDATA 'Sion' }
$port = if ($env:SION_API_PORT) { [int]$env:SION_API_PORT } else { 8010 }
$base = "http://127.0.0.1:$port"
New-Item -ItemType Directory -Force (Join-Path $runtime 'logs'), (Join-Path $runtime 'pids') | Out-Null

function Get-Pid([string]$name) {
    $file = Join-Path $runtime "pids\$name.pid"
    if (-not (Test-Path $file)) { return $null }
    $id = [int](Get-Content $file)
    if (Get-Process -Id $id -ErrorAction SilentlyContinue) { return $id }
    Remove-Item $file -Force
    return $null
}

function Start-SionProcess([string]$name, [string[]]$arguments) {
    if (Get-Pid $name) { Write-Host "$name already running (pid $(Get-Pid $name))"; return }
    $log = Join-Path $runtime "logs\$name.log"
    $proc = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru
    Set-Content -Path (Join-Path $runtime "pids\$name.pid") -Value $proc.Id
    Write-Host "$name started (pid $($proc.Id)), log $log"
}

function Wait-Url([string]$url, [int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try { return Invoke-RestMethod -Uri $url -TimeoutSec 2 } catch { Start-Sleep -Seconds 1 }
    }
    return $null
}

switch ($Action) {
    'start' {
        if ($env:SION_GRAPHRAG_EMBED_BASE_URL -match '^http://127\.0\.0\.1:(\d+)') {
            Start-SionProcess 'embeddings' @('scripts\local_embeddings.py', '--port', $Matches[1])
            $null = Wait-Url "http://127.0.0.1:$($Matches[1])/v1/models" 180
        }
        Start-SionProcess 'api' @('-m', 'uvicorn', 'sion_api.main:create_app', '--factory', '--host', '127.0.0.1', '--port', "$port")
        $health = Wait-Url "$base/health" 60
        if ($health) { Write-Host "API ok: $base  (review UI: $base/review)" } else { Write-Warning "API did not answer; see logs in $runtime\logs" }
    }
    'status' {
        foreach ($n in 'embeddings', 'api') { Write-Host ("{0,-11} {1}" -f $n, $(if (Get-Pid $n) { "running (pid $(Get-Pid $n))" } else { 'stopped' })) }
        try {
            Invoke-RestMethod "$base/health" -TimeoutSec 3 | ConvertTo-Json -Compress | Write-Host
            $s = Invoke-RestMethod "$base/api/v1/storage/status" -TimeoutSec 5
            Write-Host "storage root: $($s.layout.root)"
            if ($s.last_export) { Write-Host "last export:  $($s.last_export.stamp) $($s.last_export.counts | ConvertTo-Json -Compress)" }
            if ($s.last_error) { Write-Warning "last export error: $($s.last_error)" }
        } catch { Write-Host 'API not reachable' }
    }
    'stop' {
        if (Get-Pid 'api') {
            try { $null = Invoke-RestMethod -Method Post "$base/api/v1/storage/export" -TimeoutSec 300; Write-Host 'final export written' }
            catch { Write-Warning "final export skipped: $($_.Exception.Message)" }
        }
        foreach ($n in 'api', 'embeddings') {
            $id = Get-Pid $n
            if ($id) { Stop-Process -Id $id -Force; Remove-Item (Join-Path $runtime "pids\$n.pid") -Force; Write-Host "$n stopped" }
        }
    }
}
