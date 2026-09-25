[CmdletBinding(DefaultParameterSetName = 'Reproduce')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Reproduce')]
    [ValidateNotNullOrEmpty()]
    [string]$BundlePath,

    [Parameter(Mandatory = $true, ParameterSetName = 'CreateFullBundle')]
    [ValidateNotNullOrEmpty()]
    [string]$SourceRepo,

    [Parameter(ParameterSetName = 'CreateFullBundle')]
    [ValidateNotNullOrEmpty()]
    [string]$OutputBundle,

    [string]$Branch = 'codex/p0-remediation-20260924',
    [string]$ExpectedCommit = '715ea4c',
    [ValidateSet('Fast', 'Full')]
    [string]$TestMode = 'Fast',
    [switch]$SkipPackaging
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked([string]$File, [string[]]$Arguments, [string]$WorkingDirectory) {
    Write-Host "==> $File $($Arguments -join ' ')" -ForegroundColor Cyan
    $pythonPath = $env:PYTHONPATH
    $pythonHome = $env:PYTHONHOME
    $pipPrefix = $env:PIP_PREFIX
    $pipTarget = $env:PIP_TARGET
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PIP_PREFIX -ErrorAction SilentlyContinue
    Remove-Item Env:PIP_TARGET -ErrorAction SilentlyContinue
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $File @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')" }
    }
    finally {
        Pop-Location
        if ($null -ne $pythonPath) { $env:PYTHONPATH = $pythonPath }
        if ($null -ne $pythonHome) { $env:PYTHONHOME = $pythonHome }
        if ($null -ne $pipPrefix) { $env:PIP_PREFIX = $pipPrefix }
        if ($null -ne $pipTarget) { $env:PIP_TARGET = $pipTarget }
    }
}

function New-FullHistoryBundle {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Ref,
        [string]$Destination
    )

    $repo = (Resolve-Path -LiteralPath $Repository).Path
    $repoRoot = (& git -C $repo rev-parse --show-toplevel).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Not a Git worktree: $repo" }
    $shallow = (& git -C $repo rev-parse --is-shallow-repository).Trim()
    if ($LASTEXITCODE -ne 0 -or $shallow -ne 'false') {
        throw 'Cannot create a full-history bundle from a shallow repository. Fetch the missing history into a non-shallow repository first.'
    }
    $commit = (& git -C $repo rev-parse $Ref).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Bundle source ref not found: $Ref" }

    if (-not $Destination) {
        $artifactDir = Join-Path $repoRoot 'artifacts'
        New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
        $Destination = Join-Path $artifactDir ("full-{0}-{1}.bundle" -f ($Ref -replace '[^A-Za-z0-9._-]', '_'), $commit.Substring(0, 12))
    }
    $parent = Split-Path -Parent ([IO.Path]::GetFullPath($Destination))
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $output = [IO.Path]::GetFullPath($Destination)
    if (Test-Path -LiteralPath $output) { throw "Refusing to overwrite existing bundle: $output" }

    Invoke-Checked 'git' @('-C', $repoRoot, 'bundle', 'create', $output, "refs/heads/$Ref") (Get-Location).Path
    Invoke-Checked 'git' @('-C', $repoRoot, 'bundle', 'verify', $output) (Get-Location).Path
    Write-Host "Created full-history bundle at $output" -ForegroundColor Green
    return $output
}

if ($PSCmdlet.ParameterSetName -eq 'CreateFullBundle') {
    New-FullHistoryBundle -Repository $SourceRepo -Ref $Branch -Destination $OutputBundle
    return
}

$bundle = (Resolve-Path -LiteralPath $BundlePath).Path
if (-not (Test-Path -LiteralPath $bundle -PathType Leaf)) { throw "Bundle not found: $bundle" }
if (-not $ExpectedCommit) { throw 'ExpectedCommit is required' }

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("sion-bundle-repro-" + [guid]::NewGuid().ToString('N'))
$verifyRepo = Join-Path $tempRoot 'verify-repo'
$checkout = Join-Path $tempRoot 'checkout'
$venv = Join-Path $tempRoot 'venv'
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    # Verify in an empty repository. Running from the source worktree can mask
    # a missing prerequisite because Git may find that object locally.
    Invoke-Checked 'git' @('init', '--quiet', $verifyRepo) (Get-Location).Path
    Invoke-Checked 'git' @('-C', $verifyRepo, 'bundle', 'verify', $bundle) (Get-Location).Path

    # --no-local forces the transport path even for a local bundle. No --depth is
    # permitted: the complete ancestry in the verified bundle is mandatory.
    Invoke-Checked 'git' @('clone', '--no-local', '--branch', $Branch, $bundle, $checkout) (Get-Location).Path
    Invoke-Checked 'git' @('-C', $checkout, 'rev-parse', 'HEAD') (Get-Location).Path
    $head = (& git -C $checkout rev-parse HEAD).Trim()
    if (-not $head.StartsWith($ExpectedCommit, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Expected commit $ExpectedCommit, cloned $head"
    }
    Invoke-Checked 'git' @('-C', $checkout, 'branch', '--show-current') (Get-Location).Path
    Invoke-Checked 'git' @('-C', $checkout, 'status', '--porcelain=v1', '--branch') (Get-Location).Path
    if ((& git -C $checkout rev-parse --is-shallow-repository).Trim() -ne 'false') { throw 'Clean-room checkout unexpectedly has shallow history.' }

    Invoke-Checked 'python' @('-m', 'venv', $venv) (Get-Location).Path
    $py = Join-Path $venv 'Scripts/python.exe'
    # ensurepip is local and deterministic; do not upgrade pip in the gate.
    Invoke-Checked $py @('-m', 'ensurepip', '--upgrade') (Get-Location).Path
    Invoke-Checked $py @('-m', 'pip', 'install', '-e', '.[test]') $checkout
    $testArgs = if ($TestMode -eq 'Full') { @('-m', 'pytest', '-q') } else {
        @('-m', 'pytest', '-q', 'tests/test_auth.py', 'tests/test_dlp.py', 'tests/test_evidence_contract.py', 'tests/test_bridge_upsert.py', 'tests/test_sync_atomic.py', 'tests/test_automation_security.py', 'tests/test_frozen_contract.py')
    }
    Invoke-Checked $py $testArgs $checkout
    Invoke-Checked $py @('-m', 'compileall', '-q', 'apps', 'packages', 'scripts', 'sync') $checkout
    Invoke-Checked $py @('-m', 'pip', 'check') $checkout
    Invoke-Checked $py @('scripts/verify-release-lock.py') $checkout

    if (-not $SkipPackaging) {
        $dist = Join-Path $checkout 'dist'
        Invoke-Checked $py @('-m', 'pip', 'install', 'build') $checkout
        Invoke-Checked $py @('-m', 'build', '--wheel', '--outdir', $dist, '.') $checkout
        $wheel = Get-ChildItem -LiteralPath $dist -Filter '*.whl' | Select-Object -First 1
        if (-not $wheel) { throw 'Wheel build produced no wheel' }
        $smoke = Join-Path $tempRoot 'smoke-venv'
        Invoke-Checked $py @('-m', 'venv', $smoke) (Get-Location).Path
        $smokePy = Join-Path $smoke 'Scripts/python.exe'
        Invoke-Checked $smokePy @('-m', 'pip', 'install', $wheel.FullName) (Get-Location).Path
        Invoke-Checked $smokePy @('-c', 'import sion_api, sion_ingestion, sion_drive_store') (Get-Location).Path
    } else { Write-Host 'Packaging skipped by request; Docker/EXE rebuild is not repeated.' }
    Write-Host "Bundle reproduction passed: $TestMode gate at $head" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
