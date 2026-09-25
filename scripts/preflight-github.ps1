[CmdletBinding()]
param(
    [string]$RepoPath = (Get-Location).Path,
    [string]$ExpectedBranch = 'codex/p0-remediation-20260924',
    [string]$ExpectedHead = '715ea4c',
    [string]$OutputDirectory = '',
    [switch]$SkipRemote
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath $RepoPath).Path
if (-not $OutputDirectory) {
    $sessionTmp = Join-Path $repo '..\..\tmp'
    $OutputDirectory = (Resolve-Path -LiteralPath $sessionTmp -ErrorAction SilentlyContinue).Path
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path ([IO.Path]::GetTempPath()) 'github-preflight' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$jsonPath = Join-Path $OutputDirectory "github-preflight-$stamp.json"
$mdPath = Join-Path $OutputDirectory "github-preflight-$stamp.md"

function Redact([string]$value) {
    if ($null -eq $value) { return $null }
    # Redact before any value is written to a report. Keep only harmless labels.
    $v = $value
    $v = $v -replace '(?i)(authorization\s*:\s*bearer\s+|bearer\s+)[A-Za-z0-9._~+/=-]+', '$1[REDACTED]'
    $v = $v -replace '(?i)((?:access[_-]?token|refresh[_-]?token|token|password|passwd|secret|client[_-]?secret|oauth[_-]?token)\s*[:=]\s*)[^\s,;]+', '$1[REDACTED]'
    $v = $v -replace '(?i)(gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+|oauth[_=-][A-Za-z0-9._-]+)', '[REDACTED]'
    $v = $v -replace '(?i)([?&][^\s=]+)=([^&\s]+)', '$1=[REDACTED]'
    $v = $v -replace '(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[REDACTED_EMAIL]'
    $v = $v -replace '(?i)((?:email|e-mail|username|user|login|sender|recipient|from|to)\s*[:=]\s*)[^\s,;]+', '$1[REDACTED]'
    return $v
}
function Run-ReadOnly([string]$File, [string[]]$Arguments) {
    try {
        $out = & $File @Arguments 2>&1 | Out-String
        [pscustomobject]@{ command = (@($File) + $Arguments) -join ' '; exit_code = $LASTEXITCODE; output = Redact $out.Trim() }
    } catch {
        [pscustomobject]@{ command = (@($File) + $Arguments) -join ' '; exit_code = 127; output = Redact $_.Exception.Message }
    }
}
function Text-Value($result) { if ($result.output) { return $result.output } else { return '' } }
function Add-Check([string]$name, $result, [string]$status = $null) {
    $code = if ($null -ne $result.exit_code) { [int]$result.exit_code } else { 0 }
    $s = $status; if (-not $s) { $s = if ($code -eq 0) { 'available' } else { 'unavailable' } }
    [pscustomobject]@{ name = $name; status = $s; exit_code = $code; command = $result.command; output = $result.output }
}
Set-Location -LiteralPath $repo
$checks = @()
$checks += Add-Check 'remote' (Run-ReadOnly 'git' @('remote','-v'))
$statusResult = Run-ReadOnly 'git' @('status','--short','--branch')
$checks += Add-Check 'git_status' $statusResult
$branchResult = Run-ReadOnly 'git' @('branch','--show-current')
$headResult = Run-ReadOnly 'git' @('rev-parse','HEAD')
$checks += Add-Check 'branch' $branchResult
$checks += Add-Check 'head' $headResult
$remote = $null
$remoteResult = $checks | Where-Object name -eq 'remote' | Select-Object -First 1
if ($remoteResult.output -match '(?m)^(\S+)\s+(\S+)\s+\(fetch\)') { $remote = Redact $Matches[2] }
if (-not $SkipRemote) {
    $checks += Add-Check 'ls_remote' (Run-ReadOnly 'git' @('ls-remote','--heads','origin'))
} else { $checks += [pscustomobject]@{ name='ls_remote'; status='skipped'; exit_code=0; command='git ls-remote --heads origin'; output='Skipped by -SkipRemote' } }
$ghStatus = $null
$ghRepo = $null
$ghApiProtection = $null
$ghApiChecks = $null
$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($gh) {
    $ghStatus = Run-ReadOnly 'gh' @('auth','status')
    # gh auth status can contain username, token prefixes, scopes, and host details.
    # Never persist its command or output: record only authentication and exit code.
    $checks += [pscustomobject]@{
        name = 'gh_auth'
        status = if ([int]$ghStatus.exit_code -eq 0) { 'authenticated' } else { 'unauthenticated' }
        exit_code = [int]$ghStatus.exit_code
        authenticated = ([int]$ghStatus.exit_code -eq 0)
    }
    $ghRepo = Run-ReadOnly 'gh' @('repo','view','--json','nameWithOwner,isFork,parent,defaultBranchRef,viewerPermission')
    $checks += Add-Check 'repository_permissions' $ghRepo
    if ($ghStatus.exit_code -eq 0) {
        $repoName = ''
        try { $repoName = (($ghRepo.output | ConvertFrom-Json).nameWithOwner) } catch {}
        if ($repoName) {
            $ghApiProtection = Run-ReadOnly 'gh' @('api',("repos/$repoName/branches/$ExpectedBranch/protection"))
            $checks += Add-Check 'branch_protection' $ghApiProtection
            $ghApiChecks = Run-ReadOnly 'gh' @('api',("repos/$repoName/commits/$ExpectedHead/check-runs"))
            $checks += Add-Check 'required_checks' $ghApiChecks
        }
    }
} else {
    $checks += [pscustomobject]@{
        name = 'gh_auth'
        status = 'unavailable'
        exit_code = 127
        authenticated = $false
    }
}
$branchName = (Text-Value $branchResult).Trim(); $headSha = (Text-Value $headResult).Trim()
$report = [ordered]@{ generated_at = (Get-Date).ToUniversalTime().ToString('o'); repository_path=$repo; expected_branch=$ExpectedBranch; expected_head=$ExpectedHead; actual_branch=$branchName; actual_head=$headSha; branch_matches=($branchName -eq $ExpectedBranch); head_matches=($headSha.StartsWith($ExpectedHead)); remote=$remote; remote_read_only=$true; mutation_performed=$false; checks=$checks; capabilities=[ordered]@{ fork='gh repository view when available'; permission='gh repository view viewerPermission when available'; branch_divergence='git status, ls-remote, and branch/head output; remote API query is intentionally not required'; required_checks='GitHub check-runs API when gh auth is available'; branch_protection='GitHub branch protection API when gh auth is available' } }
$json = $report | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($jsonPath, $json, [Text.UTF8Encoding]::new($false))
$md = @("# GitHub preflight", "", "- Repository: ``$repo``", "- Expected branch: ``$ExpectedBranch``; actual: ``$branchName``", "- Expected HEAD: ``$ExpectedHead``; actual: ``$headSha``", "- Remote inspected: ``$remote``", "- Mutation performed: **no** (read-only only)", "", "## Results", '')
foreach ($c in $checks) { $md += "- **$($c.name)**: $($c.status) (exit $($c.exit_code))" }
$md += @("", "## Safety", "", "No push, PR, repository setting, or remote mutation command was used. Command output is credential-redacted before report storage.")
[IO.File]::WriteAllText($mdPath, $md, [Text.UTF8Encoding]::new($false))
Write-Output $jsonPath; Write-Output $mdPath
