<#
.SYNOPSIS
  One-command switch of the live AEC host stack from the archived standalone checkout
  (khs0927/Ontology, e.g. C:\CODE\Ontology) to the Sion monorepo (packages\aec).
  Dry-run by default: nothing is changed unless -Apply is given.
.DESCRIPTION
  Steps (each mutating step is logged; with no -Apply it only prints "[DRY-RUN] would ..."):
    1. preflight   monorepo checkout is clean and on main (warns when behind origin/main), legacy .env exists
    2. inventory   lists \AEC\ tasks (marks actions still pointing at -LegacyRoot) and AutoSync_Code_To_GDrive
    3. compose     detects the compose project + DB volume of the running aec-db container, so the same
                   named volume (<project>_aec-pgdata) is reused: no re-init, no data loss
    4. backup      exports every touched task to XML (rollback: Register-ScheduledTask -Xml), saves the
                   legacy pip freeze, optional pg_dump through the legacy backup.ps1
    5. drain       legacy stop-workers.ps1 -Drain (stop file; workers finish their job), stops re-embed /
                   GraphRAG refresh, disables the \AEC\ tasks while switching
    6. env         copies .env (and docker-compose.override.yml) to packages\aec; values are never printed;
                   pins COMPOSE_PROJECT_NAME to the detected project
    7. stack       docker compose -p <project>: build api, up -d db, run --rm migrate (init-db), up -d api
    8. venv        packages\aec\.venv with Python >= 3.12 (checked in preflight; an old venv is renamed to the
                   git-ignored .venv.old-<stamp>, never deleted); pip install -e
                   ".[<Extras>]" plus the monorepo root (--no-deps, shared sion_cad reader)
    9. tasks       register-bulk-tasks.ps1 + register-host-tasks.ps1 from packages\aec\scripts\ops;
                   removes the one-shot AEC-Ops-FinalWrap / AEC-Ops-FinalCheck tasks; re-enables the \AEC\
                   tasks except any that still target -LegacyRoot (those stay disabled, WARN)
   10. autosync    AutoSync_Code_To_GDrive must be disabled (disabled here when present and enabled)
   11. health      GET /healthz and /v1/kg/stats on 127.0.0.1:<AEC_API_HOST_PORT from .env, default 58000>
                   (or -ApiUrl; Bearer token read from .env, never printed)
   12. graphrag    starts \AEC\AEC-GraphRAG-Refresh (incremental kg-build + kg-summarize = re-index)
   13. resume      new stop-workers.ps1 -Resume (unless -NoResume)
  The legacy checkout is left untouched (rollback = re-import the XML backups, see the runbook
  packages\aec\docs\SWITCH-TO-MONOREPO.ko.md).
.EXAMPLE
  # dry run (default): prints the plan and checks preconditions
  powershell -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -LegacyRoot C:\CODE\Ontology
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -LegacyRoot C:\CODE\Ontology -Apply
.EXAMPLE
  # parse this script and the ops scripts it calls, and prove native argv survives
  # Windows PowerShell 5.1 and PowerShell 7 (no legacy checkout, no -Apply)
  powershell -NoProfile -ExecutionPolicy Bypass -File packages\aec\scripts\ops\switch-to-monorepo.ps1 -SelfTest
#>
[CmdletBinding()]
param(
    [string]$MonorepoRoot = '',
    [string]$LegacyRoot = 'C:\CODE\Ontology',
    [switch]$Apply,
    [string]$ComposeProject = '',
    [string]$DataRoot = '',
    [string]$LogDir = '',
    [string]$Config = '',
    [int]$Workers = 2,
    [string]$OllamaHome = '',
    [string]$Extras = 'operational,pdf,bim,ocr,cad',
    [string]$Python = '',
    [int]$DrainTimeoutMin = 30,
    [string[]]$StaleTasks = @('AEC-Ops-FinalWrap', 'AEC-Ops-FinalCheck'),
    [string]$AutoSyncTask = 'AutoSync_Code_To_GDrive',
    [string]$ApiUrl = '',
    [switch]$SkipBackup,
    [switch]$SkipVenv,
    [switch]$SkipCompose,
    [switch]$SkipGraphRag,
    [switch]$NoResume,
    [switch]$AllowNotMain,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$DryRun = -not $Apply
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ps = if ($env:SystemRoot) { Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe' } else { 'pwsh' }

if (-not $MonorepoRoot) { $MonorepoRoot = Join-Path $PSScriptRoot '..\..\..\..' }
$MonorepoRoot = (Resolve-Path -LiteralPath $MonorepoRoot).Path
$AecRoot = Join-Path $MonorepoRoot 'packages\aec'
$NewOps = Join-Path $AecRoot 'scripts\ops'
$LegacyOps = Join-Path $LegacyRoot 'scripts\ops'
$LegacyEnv = Join-Path $LegacyRoot '.env'
$NewEnv = Join-Path $AecRoot '.env'

# --- .env helpers: read single keys, never echo values -------------------------------------------
function Get-DotEnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    foreach ($line in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#') -or -not $t.Contains('=')) { continue }
        $k, $v = $t.Split('=', 2)
        if ($k.Trim() -eq $Key) { return $v.Trim().Trim('"').Trim("'") }
    }
    return ''
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $lines = New-Object System.Collections.Generic.List[string]
    if (Test-Path -LiteralPath $Path) { $lines.AddRange([string[]][System.IO.File]::ReadAllLines($Path, $utf8)) }
    $done = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($Key))\s*=") { $lines[$i] = "$Key=$Value"; $done = $true }
    }
    if (-not $done) { $lines.Add("$Key=$Value") }
    [System.IO.File]::WriteAllLines($Path, $lines.ToArray(), $utf8)
}

if (-not $DataRoot) {
    $DataRoot = Get-DotEnvValue $LegacyEnv 'AEC_DATA_ROOT'
    if (-not $DataRoot -or $DataRoot.StartsWith('/')) { $DataRoot = 'D:\AECData' }  # container value -> host default
}
if (-not $ApiUrl) {
    # Same rule as docker-compose.yml ("127.0.0.1:${AEC_API_HOST_PORT:-58000}:8000").
    $apiPort = 58000
    $envPort = Get-DotEnvValue $LegacyEnv 'AEC_API_HOST_PORT'
    $parsedPort = 0
    if ($envPort -and [int]::TryParse($envPort, [ref]$parsedPort) -and $parsedPort -ge 1 -and $parsedPort -le 65535) { $apiPort = $parsedPort }
    $ApiUrl = "http://127.0.0.1:$apiPort"
}
if (-not $LogDir) { $LogDir = Join-Path $DataRoot 'bulk\logs' }
if (-not $Config) { $Config = Join-Path $DataRoot 'bulk\sources.json' }
$BackupDir = Join-Path $DataRoot "switch-backup\$stamp"
# The log directory is created after -SelfTest. A self-test must not require D:\.
$LogFile = Join-Path $LogDir "switch-to-monorepo-$stamp.log"
$script:Warnings = New-Object System.Collections.Generic.List[string]

function Write-Log([string]$Message, [string]$Level = 'INFO') {
    $line = "$(Get-Date -Format s) [$Level] $Message"
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    if ($Level -eq 'WARN') { $script:Warnings.Add($Message); Write-Warning $Message }
    elseif ($Level -eq 'ERROR') { Write-Host $line -ForegroundColor Red }
    else { Write-Host $line }
}

function Invoke-Change([string]$What, [scriptblock]$Action) {
    if ($DryRun) { Write-Log "[DRY-RUN] would $What"; return }
    Write-Log "-> $What"
    & $Action
}

# Windows PowerShell 5.1 hands native arguments to CreateProcess with a broken quoter:
# a double quote inside an argument is not escaped, so python -c 'print("venv ok")'
# arrives as print(venv and dies with SyntaxError: '(' was never closed. PowerShell 7
# on Windows does not share that bug, but the call operator is still the wrong place
# to build a command line. Escape for CommandLineToArgvW and set ProcessStartInfo.Arguments
# (the raw command-line tail). .NET does not escape that string again.
function ConvertTo-WindowsCommandLine([string[]]$ArgumentList) {
    $sb = New-Object System.Text.StringBuilder
    foreach ($argument in @($ArgumentList)) {
        if ($null -eq $argument) { $argument = '' }
        if ($sb.Length -gt 0) { [void]$sb.Append(' ') }
        $needsQuote = ($argument.Length -eq 0)
        if (-not $needsQuote) {
            foreach ($ch in $argument.ToCharArray()) {
                if ([char]::IsWhiteSpace($ch) -or $ch -eq '"') { $needsQuote = $true; break }
            }
        }
        if (-not $needsQuote) { [void]$sb.Append($argument); continue }
        [void]$sb.Append('"')
        $chars = $argument.ToCharArray()
        $idx = 0
        while ($idx -lt $chars.Length) {
            $c = $chars[$idx]
            $idx++
            if ($c -eq '\') {
                $num = 1
                while ($idx -lt $chars.Length -and $chars[$idx] -eq '\') { $idx++; $num++ }
                if ($idx -ge $chars.Length) {
                    for ($n = 0; $n -lt ($num * 2); $n++) { [void]$sb.Append('\') }
                } elseif ($chars[$idx] -eq '"') {
                    for ($n = 0; $n -lt ($num * 2 + 1); $n++) { [void]$sb.Append('\') }
                    [void]$sb.Append('"')
                    $idx++
                } else {
                    for ($n = 0; $n -lt $num; $n++) { [void]$sb.Append('\') }
                }
            } elseif ($c -eq '"') {
                [void]$sb.Append('\')
                [void]$sb.Append('"')
            } else {
                [void]$sb.Append($c)
            }
        }
        [void]$sb.Append('"')
    }
    return $sb.ToString()
}

function Resolve-NativeExe([string]$Exe) {
    if (-not $Exe) { throw 'native executable name is empty' }
    if ([System.IO.Path]::IsPathRooted($Exe) -or (Test-Path -LiteralPath $Exe)) {
        return (Resolve-Path -LiteralPath $Exe).Path
    }
    $cmd = Get-Command -Name $Exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    return $Exe
}

function Write-NativeLine([string]$Line) {
    Write-Host "    $Line"
    if (-not $script:LogFile) { return }
    $parent = Split-Path -Parent $script:LogFile
    if ($parent -and (Test-Path -LiteralPath $parent)) {
        Add-Content -LiteralPath $script:LogFile -Value "    $Line" -Encoding UTF8
    }
}

function Start-NativeProcess([string]$Exe, [string[]]$Arguments, [string]$WorkDir = '') {
    if (-not $Arguments) { $Arguments = @() }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = (Resolve-NativeExe $Exe)
    $psi.Arguments = (ConvertTo-WindowsCommandLine $Arguments)
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $psi.StandardOutputEncoding = $utf8
    $psi.StandardErrorEncoding = $utf8
    if ($WorkDir) { $psi.WorkingDirectory = (Resolve-Path -LiteralPath $WorkDir).Path }
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        if (-not $proc.Start()) { throw "failed to start $Exe" }
        # Drain both pipes together. Reading one to the end first deadlocks when the other fills.
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        $proc.WaitForExit() | Out-Null
        $stdout = $outTask.GetAwaiter().GetResult()
        $stderr = $errTask.GetAwaiter().GetResult()
        if (-not $proc.HasExited) { $proc.WaitForExit() | Out-Null }
        return [pscustomobject]@{ ExitCode = $proc.ExitCode; Stdout = $stdout; Stderr = $stderr }
    } finally {
        $proc.Dispose()
    }
}

function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$WorkDir = '') {
    $result = Start-NativeProcess -Exe $Exe -Arguments $Arguments -WorkDir $WorkDir
    foreach ($chunk in @($result.Stdout, $result.Stderr)) {
        if (-not $chunk) { continue }
        foreach ($line in ($chunk -split "`r`n|`n")) {
            if ($line -eq '') { continue }
            Write-NativeLine $line
        }
    }
    $global:LASTEXITCODE = $result.ExitCode
    if ($result.ExitCode -ne 0) { throw "$Exe $($Arguments -join ' ') failed ($($result.ExitCode))" }
}

function Invoke-OpsScript([string]$Script, [string[]]$Arguments) {
    Invoke-Native $ps (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Script) + $Arguments)
}

# The code string keeps the double quotes that PowerShell 5.1's call operator used to
# strip. Invoke-Native escapes them, so python receives print("venv ok") intact.
function Test-VenvImport([string]$Python, [int]$Attempts = 3, [int]$DelaySeconds = 5) {
    $code = 'import aec_intelligence, sion_cad.reader; print("venv ok")'
    for ($i = 1; $i -le $Attempts; $i++) {
        try { Invoke-Native $Python @('-c', $code); return }
        catch {
            if ($i -ge $Attempts) { throw }
            Write-Log "[WARN] venv import check failed (attempt $i/$Attempts), retrying in ${DelaySeconds}s"
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

function Get-AecTasks { @(Get-ScheduledTask -TaskPath '\AEC\' -ErrorAction SilentlyContinue) }

function Export-TaskXml($Task) {
    if ($DryRun) { Write-Log "[DRY-RUN] would back up $($Task.TaskPath)$($Task.TaskName) to XML"; return }
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $file = Join-Path $BackupDir (($Task.TaskPath.Trim('\') -replace '\\', '_') + '_' + $Task.TaskName + '.xml')
    Export-ScheduledTask -TaskPath $Task.TaskPath -TaskName $Task.TaskName | Set-Content -LiteralPath $file -Encoding Unicode
    Write-Log "backed up $($Task.TaskPath)$($Task.TaskName) -> $file"
}

# "$LegacyRoot" is a strict prefix of "$LegacyRoot-platform", so a bare wildcard
# match flags the freshly re-registered monorepo tasks as legacy and leaves them
# disabled (seen live on 2026-11-12: the -Apply then died starting AEC-GraphRAG-Refresh).
# Match the root only when the next character cannot extend the folder name
# (separator, quote, bracket, whitespace or end of string).
function Test-TargetsLegacyPath([string]$Text, [string]$Root) {
    if (-not $Text) { return $false }
    return $Text -match ([regex]::Escape($Root) + '(?![-\w])')
}

function Invoke-SwitchSelfTest {
    $onWindows = $true
    if (Test-Path variable:IsWindows) { $onWindows = $IsWindows }
    if (-not $onWindows) { throw '-SelfTest checks Windows command-line argv; run it with powershell.exe or pwsh on Windows' }
    Write-Host "switch-to-monorepo -SelfTest on PowerShell $($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition))"
    $toParse = @(
        $PSCommandPath,
        (Join-Path $PSScriptRoot '_common.ps1'),
        (Join-Path $PSScriptRoot 'stop-workers.ps1'),
        (Join-Path $PSScriptRoot 'backup.ps1'),
        (Join-Path $PSScriptRoot 'register-bulk-tasks.ps1'),
        (Join-Path $PSScriptRoot 'register-host-tasks.ps1')
    )
    foreach ($path in $toParse) {
        if (-not (Test-Path -LiteralPath $path)) { throw "self-test parse target missing: $path" }
        $tokens = $null
        $parseErrors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors -and @($parseErrors).Count -gt 0) {
            throw "parse error in ${path}: $($parseErrors[0].ToString())"
        }
        Write-Host "parsed $path"
    }
    $legacyCases = @(
        @{ Text = 'powershell.exe -File "C:\CODE\Ontology\scripts\ops\bulk-run.ps1" [C:\CODE\Ontology]'; Want = $true },
        @{ Text = 'powershell.exe -File "C:\CODE\Ontology-platform\packages\aec\scripts\ops\bulk-run.ps1" [C:\CODE\Ontology-platform\packages\aec]'; Want = $false },
        @{ Text = 'powershell.exe -File D:\AECData\dev\db-tune.ps1 [C:\CODE\Ontology]'; Want = $true }
    )
    foreach ($c in $legacyCases) {
        $got = Test-TargetsLegacyPath $c.Text 'C:\CODE\Ontology'
        if ($got -ne [bool]$c.Want) { throw "legacy path check: got [$got], want [$($c.Want)] for [$($c.Text)]" }
    }
    Write-Host 'legacy path prefix check ok (the root is not matched inside a longer folder name)'
    $python = Resolve-NativeExe 'python'
    if ($python -eq 'python') {
        $found = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $found -or -not $found.Source) { throw 'self-test needs python on PATH' }
        $python = $found.Source
    }
    foreach ($snippet in @('print("venv ok")', "print('venv ok')")) {
        $ran = Start-NativeProcess -Exe $python -Arguments @('-c', $snippet)
        $got = ($ran.Stdout -replace "`r", '').Trim()
        if ($ran.ExitCode -ne 0 -or $got -ne 'venv ok') {
            throw "python -c [$snippet] exit=$($ran.ExitCode) stdout=[$got] stderr=[$($ran.Stderr)]"
        }
        Write-Host "python -c round-trip ok: $snippet"
    }
    $cases = @(
        'import aec_intelligence, sion_cad.reader; print("venv ok")',
        'import aec_intelligence, sion_cad.reader; print(''venv ok'')',
        'trailing\',
        'a "quote" inside',
        'plain',
        ''
    )
    # BEGIN/END markers keep an empty argument (a blank base64 line) from being dropped.
    $probe = 'import sys,base64; sys.stdout.write("BEGIN\n"); [sys.stdout.write(base64.b64encode(a.encode("utf-8")).decode("ascii")+"\n") for a in sys.argv[1:]]; sys.stdout.write("END\n")'
    $echo = Start-NativeProcess -Exe $python -Arguments (@('-c', $probe) + $cases)
    if ($echo.ExitCode -ne 0) { throw "argv probe failed ($($echo.ExitCode)): $($echo.Stderr)" }
    $raw = ($echo.Stdout -replace "`r", '').TrimEnd("`n")
    $parts = [regex]::Split($raw, "`n")
    $begin = [array]::IndexOf($parts, 'BEGIN')
    $end = [array]::IndexOf($parts, 'END')
    if ($begin -lt 0 -or $end -le $begin) { throw "argv probe markers missing: [$raw] stderr=[$($echo.Stderr)]" }
    $encoded = @($parts[($begin + 1)..($end - 1)])
    if ($encoded.Count -ne $cases.Count) { throw "argv count $($encoded.Count) != $($cases.Count); raw=[$raw]" }
    for ($i = 0; $i -lt $cases.Count; $i++) {
        $text = ''
        if ($encoded[$i]) { $text = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$encoded[$i])) }
        if ($text -ne [string]$cases[$i]) { throw "argv[$i] got [$text] expected [$($cases[$i])]" }
    }
    Write-Host "argv round-trip ok ($($cases.Count) arguments, including the historical venv check)"
}

if ($SelfTest) {
    try { Invoke-SwitchSelfTest }
    catch {
        Write-Host "SELF-TEST FAILED: $($_.Exception.Message)"
        exit 1
    }
    Write-Host 'SELF-TEST OK'
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Log "switch-to-monorepo ($(if ($DryRun) { 'DRY-RUN, add -Apply to execute' } else { 'APPLY' }))"
Write-Log "monorepo=$MonorepoRoot legacy=$LegacyRoot data=$DataRoot log=$LogFile"

# --- 1. preflight ----------------------------------------------------------------------------------
foreach ($p in @($AecRoot, (Join-Path $AecRoot 'docker-compose.yml'), (Join-Path $NewOps 'register-host-tasks.ps1'),
        (Join-Path $NewOps 'register-bulk-tasks.ps1'), (Join-Path $NewOps 'stop-workers.ps1'))) {
    if (-not (Test-Path -LiteralPath $p)) { throw "monorepo file missing: $p" }
}
if (-not (Test-Path -LiteralPath $LegacyEnv)) { throw "legacy .env not found: $LegacyEnv (nothing to migrate?)" }
$dirty = @(& git -C $MonorepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "git status failed in $MonorepoRoot" }
if ($dirty.Count) { throw "monorepo checkout is not clean ($($dirty.Count) change(s)); commit or stash first" }
$branch = (& git -C $MonorepoRoot rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'main' -and -not $AllowNotMain) { throw "monorepo checkout is on '$branch', expected main" }
$head = (& git -C $MonorepoRoot rev-parse --short HEAD).Trim()
Write-Log "monorepo clean, branch=$branch head=$head"
$prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& git -C $MonorepoRoot fetch --quiet origin main 2>$null
if ($LASTEXITCODE -eq 0) {
    $behind = (& git -C $MonorepoRoot rev-list --count 'HEAD..origin/main' 2>$null)
    if ($behind -and [int]$behind -gt 0) { Write-Log "monorepo is $behind commit(s) behind origin/main (git pull first?)" 'WARN' }
} else { Write-Log 'git fetch failed (offline?); skipping the behind-origin check' 'WARN' }
$ErrorActionPreference = $prevEap

# Resolve a Python 3.12+ interpreter for the host venv now, before anything is drained or disabled:
# the monorepo root (pip install -e $MonorepoRoot) requires Python >= 3.12, while the archived AEC
# venv may legitimately be 3.11. An explicit -Python must satisfy the floor; otherwise the legacy
# venv's base interpreter is reused only when it is new enough, then the py launcher, then PATH.
$MinPython = [version]'3.12'
function Get-PythonVersion([string]$Exe) {
    try {
        $result = Start-NativeProcess -Exe $Exe -Arguments @('-c', 'import sys; print(*sys.version_info[:2], sep=chr(46))')
        $out = @($result.Stdout -split "`r`n|`n" | Where-Object { $_ -match '^\d+\.\d+$' } | Select-Object -Last 1)
        if ($result.ExitCode -eq 0 -and $out) { return [version]([string]$out) }
    } catch { }
    return $null
}
function Resolve-PyLauncher([string]$Tag) {
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $launcher -or -not $launcher.Source) { return '' }
    try {
        $result = Start-NativeProcess -Exe $launcher.Source -Arguments @("-$Tag", '-c', 'import sys; print(sys.executable)')
        $exe = @($result.Stdout -split "`r`n|`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
        if ($result.ExitCode -eq 0 -and $exe -and (Test-Path -LiteralPath ([string]$exe).Trim())) { return ([string]$exe).Trim() }
    } catch { }
    return ''
}
if (-not $SkipVenv) {
    if ($Python) {
        $pyVersion = Get-PythonVersion $Python
        if (-not $pyVersion -or $pyVersion -lt $MinPython) {
            throw "-Python $Python is $(if ($pyVersion) { $pyVersion } else { 'not runnable' }); the monorepo requires Python >= $MinPython"
        }
    } else {
        $candidates = New-Object System.Collections.Generic.List[string]
        $cfg = Join-Path $LegacyRoot '.venv\pyvenv.cfg'
        $home0 = if (Test-Path -LiteralPath $cfg) { ((Get-Content -LiteralPath $cfg | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', '') } else { '' }
        if ($home0 -and (Test-Path -LiteralPath (Join-Path $home0 'python.exe'))) { $candidates.Add((Join-Path $home0 'python.exe')) }
        foreach ($tag in @('3.13', '3.12')) { $found = Resolve-PyLauncher $tag; if ($found) { $candidates.Add($found) } }
        $candidates.Add('python')
        foreach ($candidate in $candidates) {
            $v = Get-PythonVersion $candidate
            if ($v -and $v -ge $MinPython) { $Python = $candidate; $pyVersion = $v; break }
            Write-Log "python candidate $candidate is $(if ($v) { $v } else { 'not runnable' }) (< $MinPython); skipped"
        }
        if (-not $Python) { throw "no Python >= $MinPython found (install it or pass -Python <path to python.exe>); nothing was changed" }
    }
    Write-Log "host venv interpreter: $Python (Python $pyVersion)"
}

# --- 2. inventory ----------------------------------------------------------------------------------
$tasks = Get-AecTasks
foreach ($t in $tasks) {
    $args0 = ($t.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) [$($_.WorkingDirectory)]" }) -join ' | '
    $legacy = Test-TargetsLegacyPath $args0 $LegacyRoot
    Write-Log ("task {0}{1} state={2} legacy={3}" -f $t.TaskPath, $t.TaskName, $t.State, $legacy)
}
$autoSync = @(Get-ScheduledTask -TaskName $AutoSyncTask -ErrorAction SilentlyContinue)
if ($autoSync.Count) { foreach ($a in $autoSync) { Write-Log "task $($a.TaskPath)$($a.TaskName) state=$($a.State)" } }
else { Write-Log "$AutoSyncTask not registered (ok)" }

# --- 3. compose project / volume -------------------------------------------------------------------
$docker = Get-Command docker -ErrorAction SilentlyContinue
# Go templates are passed WITHOUT embedded double quotes and parsed as JSON here: Windows PowerShell 5.1
# strips inner double quotes from native arguments, which broke '{{ index .Config.Labels "..." }}'
# ("function com not defined") and silently skipped the volume-reuse check.
function Get-DockerJson([string[]]$Arguments) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $raw = (& docker @Arguments 2>$null) -join "`n"
        if ($LASTEXITCODE -ne 0 -or -not "$raw".Trim() -or "$raw".Trim() -eq 'null') { return $null }
        return ($raw | ConvertFrom-Json)
    } catch { return $null } finally { $ErrorActionPreference = $prev }
}
function Get-AecDbInfo {
    $info = [pscustomobject]@{ Reachable = $false; Found = $false; Project = ''; Volume = '' }
    if (-not $docker) { return $info }
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & docker version --format '{{json .Server.Version}}' 2>$null | Out-Null
    $reachable = ($LASTEXITCODE -eq 0)
    & docker container inspect aec-db --format '{{json .Id}}' 2>$null | Out-Null
    $found = $reachable -and ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    $info.Reachable = $reachable
    if (-not $found) { return $info }
    $info.Found = $true
    $labels = Get-DockerJson @('container', 'inspect', 'aec-db', '--format', '{{json .Config.Labels}}')
    if ($labels) {
        $prop = $labels.PSObject.Properties['com.docker.compose.project']
        if ($prop -and "$($prop.Value)".Trim()) { $info.Project = "$($prop.Value)".Trim() }
    }
    foreach ($m in @(Get-DockerJson @('container', 'inspect', 'aec-db', '--format', '{{json .Mounts}}'))) {
        if ($m -and $m.Destination -eq '/var/lib/postgresql/data' -and $m.Name) { $info.Volume = "$($m.Name)".Trim() }
    }
    return $info
}
function ConvertTo-ComposeProjectName([string]$Name) {
    # docker compose project names: lower-case letters, digits, '-' and '_', starting with a letter or digit
    return (($Name.ToLowerInvariant() -replace '[^a-z0-9_-]', '') -replace '^[^a-z0-9]+', '')
}

# Project name precedence: -ComposeProject > running aec-db compose label (authoritative; must agree with an
# explicit/.env value) > .env COMPOSE_PROJECT_NAME > prefix of aec-db's <project>_aec-pgdata volume >
# the only existing *_aec-pgdata volume > legacy folder name (compose default; WARN).
$projectSource = ''
if ($ComposeProject) { $projectSource = '-ComposeProject' }
else {
    $ComposeProject = Get-DotEnvValue $LegacyEnv 'COMPOSE_PROJECT_NAME'
    if ($ComposeProject) { $projectSource = 'legacy .env COMPOSE_PROJECT_NAME' }
}
$db = Get-AecDbInfo
$dbVolume = $db.Volume
if ($docker -and -not $db.Reachable) { Write-Log 'docker is installed but the daemon is not reachable (Docker Desktop stopped?): aec-db project/volume could not be checked' 'WARN' }
elseif ($db.Reachable -and -not $db.Found) { Write-Log 'container aec-db not found on this docker daemon' 'WARN' }
if ($db.Project) {
    if ($ComposeProject -and $db.Project -ne $ComposeProject) {
        throw "aec-db belongs to compose project '$($db.Project)' but $projectSource says '$ComposeProject'"
    }
    $ComposeProject = $db.Project; $projectSource = 'aec-db compose label'
}
if (-not $ComposeProject -and $dbVolume -match '^(.+)_aec-pgdata$') {
    $ComposeProject = $Matches[1]; $projectSource = "aec-db volume $dbVolume"
}
if (-not $ComposeProject -and $db.Reachable) {
    $prevVol = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $volumes = @(& docker volume ls --format '{{.Name}}' 2>$null | Where-Object { "$_" -match '^.+_aec-pgdata$' })
    $ErrorActionPreference = $prevVol
    if ($volumes.Count -eq 1) {
        $ComposeProject = ($volumes[0] -replace '_aec-pgdata$', ''); $projectSource = "only existing volume $($volumes[0])"
    } elseif ($volumes.Count -gt 1) {
        $msg = "several *_aec-pgdata volumes exist ($($volumes -join ', ')); pass -ComposeProject to pick the live one"
        if ($DryRun) { Write-Log $msg 'WARN' } else { throw $msg }
    }
}
if (-not $ComposeProject) {
    # docker compose default project name = lower-cased folder name of the legacy checkout
    $ComposeProject = ConvertTo-ComposeProjectName (Split-Path -Leaf $LegacyRoot)
    $projectSource = 'legacy folder name (compose default)'
    Write-Log "compose project not detectable; assuming '$ComposeProject' from the legacy folder name" 'WARN'
}
$normalized = ConvertTo-ComposeProjectName $ComposeProject
if (-not $normalized) { throw "invalid compose project name '$ComposeProject' (from $projectSource)" }
if ($normalized -ne $ComposeProject) {
    if ($db.Project) { throw "aec-db compose label '$ComposeProject' is not a valid compose project name" }
    Write-Log "compose project '$ComposeProject' normalized to '$normalized'" 'WARN'
    $ComposeProject = $normalized
}
$expectedVolume = "${ComposeProject}_aec-pgdata"
if ($dbVolume -and $dbVolume -ne $expectedVolume) {
    throw "aec-db uses volume '$dbVolume', expected '$expectedVolume': refusing (a new project would init an empty DB)"
}
Write-Log "compose project source: $projectSource; aec-db found=$($db.Found) volume=$(if ($dbVolume) { $dbVolume } else { '<unknown>' }); api=$ApiUrl"
Write-Log "compose project=$ComposeProject db volume=$expectedVolume (reused, never re-initialised)"

# --- 4. backups ------------------------------------------------------------------------------------
foreach ($t in $tasks) { Export-TaskXml $t }
foreach ($a in $autoSync) { Export-TaskXml $a }
$legacyPy = Join-Path $LegacyRoot '.venv\Scripts\python.exe'
Invoke-Change "save legacy pip freeze to $BackupDir" {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    if (Test-Path -LiteralPath $legacyPy) {
        $ErrorActionPreference = 'Continue'
        & $legacyPy -m pip freeze 2>$null | Set-Content -LiteralPath (Join-Path $BackupDir 'legacy-pip-freeze.txt') -Encoding UTF8
        $ErrorActionPreference = 'Stop'
    }
}

# --- 5. drain --------------------------------------------------------------------------------------
$drainScript = if (Test-Path -LiteralPath (Join-Path $LegacyOps 'stop-workers.ps1')) { Join-Path $LegacyOps 'stop-workers.ps1' } else { Join-Path $NewOps 'stop-workers.ps1' }
Invoke-Change "drain workers with $drainScript -Drain -TimeoutMin $DrainTimeoutMin" {
    Invoke-OpsScript $drainScript @('-Drain', '-TimeoutMin', "$DrainTimeoutMin")
}
Invoke-Change 'stop AEC-GraphRAG-Refresh and disable the \AEC\ tasks during the switch' {
    foreach ($t in (Get-AecTasks)) {
        if ($t.TaskName -eq 'AEC-Ollama') { continue }  # keep embeddings/LLM serving; re-registered below
        Stop-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName -ErrorAction SilentlyContinue | Out-Null
    }
}
if (-not $SkipBackup) {
    Invoke-Change 'pg_dump the aec database with the legacy backup.ps1 (pre-switch safety dump)' {
        Invoke-OpsScript (Join-Path $LegacyOps 'backup.ps1') @()
    }
}

# --- 6. .env ---------------------------------------------------------------------------------------
Invoke-Change "copy .env to $NewEnv (values not printed) and pin COMPOSE_PROJECT_NAME=$ComposeProject" {
    if (Test-Path -LiteralPath $NewEnv) {
        $same = (Get-FileHash -LiteralPath $NewEnv).Hash -eq (Get-FileHash -LiteralPath $LegacyEnv).Hash
        if (-not $same) { Copy-Item -LiteralPath $NewEnv -Destination "$NewEnv.bak-$stamp"; Write-Log "existing packages\aec\.env kept as .env.bak-$stamp" }
    }
    Copy-Item -LiteralPath $LegacyEnv -Destination $NewEnv -Force
    Set-DotEnvValue $NewEnv 'COMPOSE_PROJECT_NAME' $ComposeProject
    $override = Join-Path $LegacyRoot 'docker-compose.override.yml'
    if (Test-Path -LiteralPath $override) { Copy-Item -LiteralPath $override -Destination (Join-Path $AecRoot 'docker-compose.override.yml') -Force }
}
if (-not (Get-DotEnvValue $LegacyEnv 'AEC_API_TOKEN')) { Write-Log 'legacy .env has no AEC_API_TOKEN (run init-env.ps1 afterwards)' 'WARN' }

# --- 7. docker stack (same project name => same volume) -------------------------------------------
if (-not $SkipCompose) {
    if (-not $docker) { throw 'docker not found (start Docker Desktop or pass -SkipCompose)' }
    $c = @('compose', '-p', $ComposeProject)
    Invoke-Change "docker compose -p $ComposeProject build api (context = monorepo root)" { Invoke-Native 'docker' ($c + @('build', 'api')) $AecRoot }
    Invoke-Change "docker compose -p $ComposeProject up -d db (volume $expectedVolume)" { Invoke-Native 'docker' ($c + @('up', '-d', 'db')) $AecRoot }
    Invoke-Change "docker compose -p $ComposeProject run --rm migrate (idempotent init-db)" { Invoke-Native 'docker' ($c + @('run', '--rm', 'migrate')) $AecRoot }
    Invoke-Change "docker compose -p $ComposeProject up -d api" { Invoke-Native 'docker' ($c + @('up', '-d', 'api')) $AecRoot }
    if (-not $DryRun) {
        $after = (Get-AecDbInfo).Volume
        if ($after -ne $expectedVolume) { throw "after the switch aec-db uses volume '$after', expected '$expectedVolume'" }
        Write-Log "aec-db still on volume $after"
    }
}

# --- 8. host venv ----------------------------------------------------------------------------------
$venv = Join-Path $AecRoot '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not $SkipVenv) {
    # $Python was resolved and checked (>= $MinPython) during preflight.
    Invoke-Change "create $venv with $Python (an existing .venv is renamed to .venv.old-$stamp)" {
        if (Test-Path -LiteralPath $venv) { Rename-Item -LiteralPath $venv -NewName ".venv.old-$stamp" }
        Invoke-Native $Python @('-m', 'venv', $venv)
        Invoke-Native $venvPy @('-m', 'pip', 'install', '--upgrade', 'pip')
        Invoke-Native $venvPy @('-m', 'pip', 'install', '-e', ".[$Extras]") $AecRoot
        Invoke-Native $venvPy @('-m', 'pip', 'install', '--no-deps', '-e', $MonorepoRoot)
        Test-VenvImport $venvPy
    }
}

# --- 9. scheduled tasks from packages\aec ----------------------------------------------------------
Invoke-Change 're-register \AEC\AEC-Bulk-* from packages\aec\scripts\ops\register-bulk-tasks.ps1' {
    Invoke-OpsScript (Join-Path $NewOps 'register-bulk-tasks.ps1') @('-Config', $Config, '-Workers', "$Workers")
}
$hostArgs = @()
if ($OllamaHome) { $hostArgs += @('-OllamaHome', $OllamaHome) }
Invoke-Change 're-register \AEC\AEC-Ollama/Reembed/WSL-Reclaim/GraphRAG-Refresh from packages\aec\scripts\ops\register-host-tasks.ps1' {
    Invoke-OpsScript (Join-Path $NewOps 'register-host-tasks.ps1') $hostArgs
}
foreach ($name in $StaleTasks) {
    $st = Get-ScheduledTask -TaskPath '\AEC\' -TaskName $name -ErrorAction SilentlyContinue
    if (-not $st) { Write-Log "stale one-shot task $name not present (ok)"; continue }
    Invoke-Change "remove stale one-shot task \AEC\$name (XML backed up)" {
        Unregister-ScheduledTask -TaskPath '\AEC\' -TaskName $name -Confirm:$false
    }
}
if (-not $DryRun) {
    foreach ($t in (Get-AecTasks)) {
        $a = ($t.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -join ' '
        if (Test-TargetsLegacyPath $a $LegacyRoot) {
            # Not managed by the register scripts and still running archived code against the live DB:
            # keep it disabled (XML backup above) until it is migrated by hand.
            if ($t.State -ne 'Disabled') {
                Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName -ErrorAction SilentlyContinue | Out-Null
            }
            Write-Log "task $($t.TaskName) still points at $LegacyRoot (not managed by the register scripts): left DISABLED; migrate it, then enable it" 'WARN'
            continue
        }
        if ($t.State -eq 'Disabled') {
            Enable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName | Out-Null
            Write-Log "re-enabled $($t.TaskName)"
        }
    }
}

# --- 10. AutoSync_Code_To_GDrive must stay disabled ------------------------------------------------
foreach ($a in $autoSync) {
    if ($a.State -eq 'Disabled') { Write-Log "$($a.TaskPath)$($a.TaskName) already disabled (ok)"; continue }
    Invoke-Change "disable $($a.TaskPath)$($a.TaskName) (code sync to Drive is replaced by Git + Drive snapshots)" {
        Disable-ScheduledTask -TaskPath $a.TaskPath -TaskName $a.TaskName | Out-Null
    }
}

# --- 11. health ------------------------------------------------------------------------------------
function Test-AecHealth {
    $ok = $false
    for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
        try { Invoke-RestMethod -Uri "$ApiUrl/healthz" -TimeoutSec 5 | Out-Null; $ok = $true } catch { Start-Sleep -Seconds 4 }
    }
    if (-not $ok) { Write-Log "API $ApiUrl/healthz not healthy after 2 min" 'WARN'; return }
    Write-Log "API $ApiUrl/healthz ok"
    $token = Get-DotEnvValue $(if (Test-Path -LiteralPath $NewEnv) { $NewEnv } else { $LegacyEnv }) 'AEC_API_TOKEN'
    $headers = @{}
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    try {
        $stats = Invoke-RestMethod -Uri "$ApiUrl/v1/kg/stats" -Headers $headers -TimeoutSec 30
        Write-Log ("kg stats: " + ($stats | ConvertTo-Json -Compress -Depth 3))
    } catch { Write-Log "GET /v1/kg/stats failed: $($_.Exception.Message)" 'WARN' }
    finally { $token = $null; $headers = $null }
}
if ($DryRun) {
    try { Invoke-RestMethod -Uri "$ApiUrl/healthz" -TimeoutSec 5 | Out-Null; Write-Log "current API $ApiUrl/healthz ok" }
    catch { Write-Log "current API $ApiUrl/healthz not reachable" 'WARN' }
} else { Test-AecHealth }

# --- 12. GraphRAG re-index -------------------------------------------------------------------------
if (-not $SkipGraphRag) {
    Invoke-Change 'start \AEC\AEC-GraphRAG-Refresh (incremental kg-build + kg-summarize from packages\aec)' {
        Start-ScheduledTask -TaskPath '\AEC\' -TaskName 'AEC-GraphRAG-Refresh'
    }
}

# --- 13. resume ------------------------------------------------------------------------------------
if (-not $NoResume) {
    Invoke-Change 'resume workers with packages\aec\scripts\ops\stop-workers.ps1 -Resume' {
        Invoke-OpsScript (Join-Path $NewOps 'stop-workers.ps1') @('-Resume')
    }
}

Write-Log ("done: {0} warning(s); backups in {1}; log {2}" -f $script:Warnings.Count, $BackupDir, $LogFile)
if ($DryRun) { Write-Log 'dry run only: re-run with -Apply to execute' }
