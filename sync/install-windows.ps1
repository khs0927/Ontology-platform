param(
    [string]$SourceRoot = "C:\CODE",
    [string]$DeviceId = "home-bedroom",
    [int]$EveryMinutes = 5,
    [string]$RemoteProjectRoot = "C:\Users\khs09\cokacremote_shared\sion-ontology-platform"
)

$ErrorActionPreference = "Stop"
$SharedRoot = "C:\Users\khs09\cokacremote_shared"
$LogPath = Join-Path $SharedRoot "SION-DRIVE-INSTALL-LOG.txt"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Add-Candidate {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Path
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if (-not $List.Contains($Path)) { $List.Add($Path) }
}

function Find-DriveCodeRoot {
    $candidates = [System.Collections.Generic.List[string]]::new()

    if ($env:SION_DRIVE_CODE_ROOT) {
        Add-Candidate $candidates $env:SION_DRIVE_CODE_ROOT
    }

    # Common Drive for Desktop layouts. Do not assume one drive letter or one UI language.
    $drives = @(Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue |
        Where-Object { $_.Root } |
        Sort-Object @{Expression={ if ($_.Name -eq "C") { 1 } else { 0 } }}, Name)

    foreach ($drive in $drives) {
        $root = $drive.Root
        Add-Candidate $candidates (Join-Path $root ".CODE")
        Add-Candidate $candidates (Join-Path $root "내 드라이브\.CODE")
        Add-Candidate $candidates (Join-Path $root "My Drive\.CODE")
        Add-Candidate $candidates (Join-Path $root "Google Drive\.CODE")
        Add-Candidate $candidates (Join-Path $root "GoogleDrive\.CODE")
    }

    $profile = $env:USERPROFILE
    if ($profile) {
        Add-Candidate $candidates (Join-Path $profile "Google Drive\.CODE")
        Add-Candidate $candidates (Join-Path $profile "My Drive\.CODE")
        Add-Candidate $candidates (Join-Path $profile "내 드라이브\.CODE")
        Add-Candidate $candidates (Join-Path $profile "GoogleDrive\.CODE")
    }

    Write-Log "Available filesystem drives: $((@($drives | ForEach-Object { "$($_.Name)=$($_.Root)" })) -join '; ')"

    foreach ($candidate in $candidates) {
        try {
            if (Test-Path -LiteralPath $candidate -PathType Container) {
                $resolved = (Resolve-Path -LiteralPath $candidate).Path
                Write-Log "Google Drive .CODE detected: $resolved"
                return $resolved
            }
        } catch {
            # Keep searching.
        }
    }

    # Last resort: inspect only first-level folders on non-system drives.
    foreach ($drive in $drives | Where-Object { $_.Name -ne "C" }) {
        try {
            foreach ($child in Get-ChildItem -LiteralPath $drive.Root -Directory -ErrorAction SilentlyContinue) {
                $candidate = Join-Path $child.FullName ".CODE"
                if (Test-Path -LiteralPath $candidate -PathType Container) {
                    $resolved = (Resolve-Path -LiteralPath $candidate).Path
                    Write-Log "Google Drive .CODE detected by first-level scan: $resolved"
                    return $resolved
                }
            }
        } catch {
            # Keep searching.
        }
    }

    Write-Log "ERROR: .CODE was not found on any mounted filesystem drive."
    Write-Log "Checked candidates: $($candidates -join ' | ')"
    throw "Google Drive의 .CODE 폴더를 로컬 Windows에서 찾지 못했습니다. Google Drive for Desktop이 로그인되어 있고 '내 드라이브'가 탐색기에 보이는지 확인하세요. 자세한 진단은 $LogPath 에 저장했습니다."
}

New-Item -ItemType Directory -Force -Path $SharedRoot | Out-Null
Set-Content -LiteralPath $LogPath -Value "" -Encoding UTF8
Write-Log "Sion Drive Sync V2 installer started."

$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
$pythonMode = "python"
if (-not $pythonCmd) {
    $pythonCmd = Get-Command py.exe -ErrorAction SilentlyContinue
    $pythonMode = "py"
}
if (-not $pythonCmd) {
    Write-Log "ERROR: Python was not found in PATH."
    throw "Python was not found in PATH."
}
Write-Log "Python detected: $($pythonCmd.Source)"

$driveCode = Find-DriveCodeRoot
$driveRoot = Join-Path $driveCode "_sync-v2"

# The cloud-side folder already exists, but creating this local DriveFS view is harmless if it has not hydrated yet.
New-Item -ItemType Directory -Force -Path $driveRoot | Out-Null
Write-Log "Drive backup root: $driveRoot"

$installRoot = "C:\SionSync"
$stateRoot = Join-Path $installRoot "state"
New-Item -ItemType Directory -Force -Path $installRoot, $stateRoot | Out-Null

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$syncSource = Join-Path $here "sion_sync.py"
if (-not (Test-Path -LiteralPath $syncSource -PathType Leaf)) {
    Write-Log "ERROR: sync engine missing: $syncSource"
    throw "sync engine not found: $syncSource"
}
Copy-Item -LiteralPath $syncSource -Destination (Join-Path $installRoot "sion_sync.py") -Force
Write-Log "Sync engine installed."

$config = [ordered]@{
    version = 2
    device_id = $DeviceId
    drive_root = $driveRoot
    source_root = $SourceRoot
    remote_project_root = $RemoteProjectRoot
    state_root = $stateRoot
    interval_minutes = $EveryMinutes
    python_mode = $pythonMode
}
$configPath = Join-Path $installRoot "config.json"
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

# Use PowerShell, not CMD, for the recurring runner so Korean Drive paths stay Unicode-safe.
$runnerPath = Join-Path $installRoot "sync-now.ps1"
$runner = @'
$ErrorActionPreference = "Continue"
$config = Get-Content -LiteralPath "C:\SionSync\config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$sync = "C:\SionSync\sion_sync.py"
$runLog = "C:\SionSync\sync-run.log"

function Invoke-SionBackup {
    param([string]$Source, [string]$Workspace)
    if (-not $Source -or -not (Test-Path -LiteralPath $Source -PathType Container)) {
        Add-Content -LiteralPath $runLog -Value ("[{0}] [SKIP] Missing source: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Source) -Encoding UTF8
        return
    }

    $args = @(
        $sync, "backup",
        "--source", $Source,
        "--drive-root", $config.drive_root,
        "--device-id", $config.device_id,
        "--workspace-name", $Workspace,
        "--state-dir", $config.state_root
    )

    if ($config.python_mode -eq "py") {
        & py.exe -3 @args *>> $runLog
    } else {
        & python.exe @args *>> $runLog
    }
}

Invoke-SionBackup -Source $config.source_root -Workspace "C_CODE"
Invoke-SionBackup -Source $config.remote_project_root -Workspace "SION_ONTOLOGY_REMOTE"
'@
Set-Content -LiteralPath $runnerPath -Value $runner -Encoding UTF8

$taskName = "SionDriveBackupV2"
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\SionSync\sync-now.ps1"
& schtasks.exe /Create /F /SC MINUTE /MO $EveryMinutes /TN $taskName /TR $taskCommand | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: Failed to register scheduled task. ExitCode=$LASTEXITCODE"
    throw "Failed to register scheduled task."
}

Write-Log "Scheduled task registered: $taskName every $EveryMinutes minute(s)."
Write-Log "Source C_CODE exists: $(Test-Path -LiteralPath $SourceRoot -PathType Container)"
Write-Log "Source SION_ONTOLOGY_REMOTE exists: $(Test-Path -LiteralPath $RemoteProjectRoot -PathType Container)"

Write-Log "Running initial backup..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runnerPath
$initialExit = $LASTEXITCODE
Write-Log "Initial backup runner exit code: $initialExit"

$manifestCandidate = Join-Path $driveRoot "manifests\$DeviceId"
if (Test-Path -LiteralPath $manifestCandidate) {
    Write-Log "PASS: Drive manifest folder is visible: $manifestCandidate"
} else {
    Write-Log "WARN: Manifest folder is not visible yet. Check C:\SionSync\sync-run.log"
}

Write-Log "Installer completed."
Write-Host ""
Write-Host "설치 완료. 진단 로그:"
Write-Host $LogPath
Write-Host "실행 로그: C:\SionSync\sync-run.log"
