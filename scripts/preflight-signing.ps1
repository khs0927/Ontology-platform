[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$OutputDir = $null
)

$ErrorActionPreference = 'Stop'

# Fail-closed signing policy. Only Authenticode 'Valid' counts as a signed and
# trusted release candidate. Every other state is blocked, including 'NotTrusted'
# (signature present but chain untrusted), 'NotSigned', 'UnknownError',
# 'Unavailable' and 'HashMismatch'.
$SignedStatus = 'Valid'
$BlockedStatuses = @('NotSigned', 'NotTrusted', 'UnknownError', 'Unavailable', 'HashMismatch')

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $RepoRoot 'tmp\signing-preflight'
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path

function Test-CommandAvailable([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-ArtifactRecord([string]$Path, [string]$Kind) {
    $item = Get-Item -LiteralPath $Path
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path))) -replace '-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
    try {
        $sig = Get-AuthenticodeSignature -LiteralPath $Path
        $authenticodeStatus = [string]$sig.Status
    } catch {
        $authenticodeStatus = 'Unavailable'
    }
    $version = $item.VersionInfo
    # Fail closed: only a fully valid, trusted signature is a release candidate.
    $signed = $authenticodeStatus -in @('Valid')
    $trusted = $authenticodeStatus -in @('Valid')
    $blockedStatus = $authenticodeStatus -notin @('Valid')
    $blockReason = if ($blockedStatus) {
        if ($authenticodeStatus -eq 'NotSigned') { 'Artifact is not signed.' }
        elseif ($authenticodeStatus -eq 'NotTrusted') { 'Signature is not trusted: the certificate chain could not be validated.' }
        elseif ($authenticodeStatus -eq 'HashMismatch') { 'Signature hash does not match the artifact.' }
        elseif ($authenticodeStatus -eq 'UnknownError') { 'Signature status could not be determined.' }
        else { 'Authenticode inspection is unavailable on this host.' }
    } else { $null }
    return [ordered]@{
        kind = $Kind
        path = $item.FullName
        relative_path = $item.FullName.Substring($RepoRoot.Length).TrimStart('\', '/')
        size_bytes = [int64]$item.Length
        sha256 = $hash
        file_version = if ($version.FileVersion) { $version.FileVersion } else { $null }
        product_version = if ($version.ProductVersion) { $version.ProductVersion } else { $null }
        authenticode_status = $authenticodeStatus
        signed = $signed
        trusted = $trusted
        blocked = $blockedStatus
        block_reason = $blockReason
    }
}

# Only enumerate tracked files under bin. dist executables are release candidates.
$paths = @()
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git -and (Test-Path (Join-Path $RepoRoot '.git'))) {
    $tracked = & git -C $RepoRoot ls-files -z -- bin 2>$null
    if ($LASTEXITCODE -eq 0 -and $tracked) {
        foreach ($path in ($tracked -split "`0")) {
            if ($path) {
                $full = Join-Path $RepoRoot $path
                if (Test-Path -LiteralPath $full -PathType Leaf) { $paths += [pscustomobject]@{ Path=$full; Kind='committed-bin' } }
            }
        }
    }
}
$paths += @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'dist') -File -Filter '*.exe' -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{ Path=$_.FullName; Kind='dist-exe' } })

$records = @($paths | Sort-Object Path -Unique | ForEach-Object { Get-ArtifactRecord $_.Path $_.Kind })
$artifacts = @($records)
$unsigned = @($artifacts | Where-Object { -not $_.signed })
$notTrusted = @($artifacts | Where-Object { $_.authenticode_status -eq 'NotTrusted' })
$missingCandidates = if ($artifacts.Count -eq 0) { 'No committed bin files or dist/*.exe candidates were found.' } else { $null }
$capabilities = [ordered]@{
    signtool_available = Test-CommandAvailable 'signtool'
    certificate_store_available = Test-Path 'Cert:\CurrentUser\My'
    azure_trusted_signing_env_present = [bool](@($env:AZURE_TRUSTED_SIGNING_ENDPOINT, $env:AZURE_TRUSTED_SIGNING_TOKEN, $env:AZURE_CODE_SIGNING_ENDPOINT, $env:AZURE_CODE_SIGNING_TOKEN) | Where-Object { $_ })
}
$report = [ordered]@{
    report_version = 2
    repo_root = $RepoRoot
    read_only = $true
    detect_only = $true
    capabilities = $capabilities
    signing_policy = [ordered]@{
        accepted_statuses = @($SignedStatus)
        blocked_statuses = $BlockedStatuses
        fail_closed = $true
    }
    artifacts = $artifacts
    unsigned_release_block = if ($unsigned.Count -gt 0 -or $missingCandidates) {
        $reason = if ($unsigned.Count -eq 0) { $missingCandidates }
            elseif ($notTrusted.Count -gt 0) { 'One or more release artifacts are signed but not trusted; only Authenticode Valid is accepted.' }
            else { 'One or more release artifacts are unsigned or failed signature validation.' }
        [ordered]@{
            blocked = $true
            reason = $reason
            artifact_count = $unsigned.Count
            untrusted_count = $notTrusted.Count
            blocked_artifacts = @($artifacts | Where-Object { $_.blocked } | ForEach-Object { "$($_.relative_path):$($_.authenticode_status)" })
        }
    } else { [ordered]@{ blocked = $false; reason = $null; artifact_count = 0; untrusted_count = 0; blocked_artifacts = @() } }
}
$jsonPath = Join-Path $OutputDir 'signing-preflight.json'
$mdPath = Join-Path $OutputDir 'signing-preflight.md'
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding UTF8
$lines = @('# Signing preflight', '', '- Read-only: yes', '- Detect-only: yes', '- Accepted Authenticode status: ``Valid`` (fail-closed)')
$lines += "- Signtool available: $($capabilities.signtool_available)"
$lines += "- Certificate store available: $($capabilities.certificate_store_available)"
$lines += "- Azure Trusted Signing environment present: $($capabilities.azure_trusted_signing_env_present)"
$lines += '', '## Unsigned release block', '', "- Blocked: ``$($report.unsigned_release_block.blocked)``", "- Reason: ``$($report.unsigned_release_block.reason)``"
$lines += '', '## Blocked artifacts', ''
if (@($report.unsigned_release_block.blocked_artifacts).Count -eq 0) { $lines += '- None.' } else { foreach ($entry in $report.unsigned_release_block.blocked_artifacts) { $lines += "- ``$entry``" } }
$lines += '', '## Artifacts', ''
if ($artifacts.Count -eq 0) { $lines += '- None found.' } else { foreach ($a in $artifacts) { $lines += "- ``$($a.relative_path)`` | $($a.size_bytes) bytes | SHA-256 ``$($a.sha256)`` | version ``$($a.file_version)`` / product ``$($a.product_version)`` | Authenticode: ``$($a.authenticode_status)`` | signed: ``$($a.signed)`` | trusted: ``$($a.trusted)``" } }
$lines | Set-Content -LiteralPath $mdPath -Encoding UTF8
Write-Host "JSON report: $jsonPath"
Write-Host "Markdown report: $mdPath"
if ($report.unsigned_release_block.blocked) { exit 2 }
exit 0
