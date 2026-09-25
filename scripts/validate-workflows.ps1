[CmdletBinding()]
param(
    [string]$WorkflowPath = ".github/workflows/ci.yml",
    [string]$Python = "python",
    [string]$ActionlintPath = "",
    [switch]$AllowContractFallback
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workflow = if ([IO.Path]::IsPathRooted($WorkflowPath)) { $WorkflowPath } else { Join-Path $repoRoot $WorkflowPath }
if (-not (Test-Path -LiteralPath $workflow -PathType Leaf)) { throw "Workflow not found: $workflow" }
$workflow = (Resolve-Path -LiteralPath $workflow).Path

$contract = @'
import os
import re
import sys
from pathlib import Path
import yaml

path = Path(sys.argv[1])
errors = []
try:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"contract: PyYAML parse failed: {exc}", file=sys.stderr)
    raise SystemExit(2)

if not isinstance(data, dict):
    errors.append("workflow root must be a mapping")
    jobs = {}
else:
    # PyYAML 6 follows YAML 1.1 and may parse the key `on` as True.
    if "on" not in data and True in data:
        data["on"] = data.pop(True)
    jobs = data.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        errors.append("jobs must be a non-empty mapping")
    perms = data.get("permissions")
    if perms != {"contents": "read"}:
        errors.append("top-level permissions must be exactly contents: read")
    if "concurrency" not in data:
        errors.append("concurrency is required")

    valid_env = {"github", "secrets", "vars", "inputs", "env", "runner", "strategy", "matrix", "needs", "jobs", "steps", "job"}
    action_re = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
    env_re = re.compile(r"\$\{\{\s*(env|steps|needs|job)\.[^}]+\s*\}\}")
    github_ctx = re.compile(r"\$\{\{\s*github\.[^}]+\s*\}\}")

    def check_expr(value, location):
        if not isinstance(value, str):
            return
        if "${{" in value and value.count("${{") != value.count("}}"):
            errors.append(f"{location}: unbalanced expression delimiters")
        if env_re.search(value) and not github_ctx.search(value):
            # Actionlint validates expression syntax. This contract rejects
            # accidental attempt-scope leakage while allowing job-level env use.
            if location.startswith("jobs.") and ".runs-on" in location:
                errors.append(f"{location}: expression uses job context in a run-on value")
        for match in re.finditer(r"\$\{\{\s*([^}]+?)\s*\}\}", value):
            expr = match.group(1)
            if any(token in expr for token in ("${{", "}}")):
                errors.append(f"{location}: malformed nested expression: {expr}")
            if "secrets." in expr and "github.event.pull_request.head.repo" in expr:
                errors.append(f"{location}: untrusted pull-request secret access")
        if "$${{" in value and value.replace("$${{", "") .count("${{") > 0:
            errors.append(f"{location}: suspicious escaped expression")

    def walk(value, location="root"):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{location}.{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{location}[{idx}]")
        else:
            check_expr(value, location)

    walk(data)
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            errors.append(f"job {job_name}: definition must be a mapping")
            continue
        for need in job.get("needs", []) if isinstance(job.get("needs", []), list) else [job.get("needs")]:
            if need and need not in jobs:
                errors.append(f"job {job_name}: needs unknown job {need!r}")
        if not job.get("timeout-minutes"):
            errors.append(f"job {job_name}: timeout-minutes is required")
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"job {job_name}: steps are required")
            continue
        for idx, step in enumerate(steps):
            loc = f"jobs.{job_name}.steps[{idx}]"
            if not isinstance(step, dict):
                errors.append(f"{loc}: step must be a mapping")
                continue
            uses = step.get("uses")
            run = step.get("run")
            if uses and run:
                errors.append(f"{loc}: uses and run are mutually exclusive")
            if uses and not action_re.fullmatch(str(uses)):
                errors.append(f"{loc}: action is not pinned to a full 40-hex commit SHA: {uses}")
            if not uses and not isinstance(run, str) or (uses and not str(uses).strip()):
                errors.append(f"{loc}: exactly one of uses or run is required")
            if run and step.get("shell") != "bash":
                errors.append(f"{loc}: run step must declare shell: bash")
        services = job.get("services") or {}
        if not isinstance(services, dict):
            errors.append(f"job {job_name}: services must be a mapping")
        else:
            for svc_name, svc in services.items():
                if not isinstance(svc, dict) or not svc.get("image"):
                    errors.append(f"job {job_name}: service {svc_name} requires image")
                if not svc.get("options", ""):
                    errors.append(f"job {job_name}: service {svc_name} requires health options")
        env = job.get("env", {})
        if not isinstance(env, dict):
            errors.append(f"job {job_name}: env must be a mapping")

if errors:
    for error in errors:
        print(f"contract: {error}", file=sys.stderr)
    raise SystemExit(1)
print("contract: PyYAML parse and workflow contract passed")
'@

$tempRoot = $null
try {
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("aside-actionlint-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot | Out-Null

    if (-not $ActionlintPath) {
        $version = "1.7.12"
        $arch = if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq [Runtime.InteropServices.Architecture]::Arm64) { "arm64" } else { "amd64" }
        $expected = "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9"
        if ($arch -ne "amd64") {
            $expected = "cadcf7ea4efe3a68728893813643cebe1185e5b1d4be5b96245f65c9a4d5ea41"
        }
        $zip = Join-Path $tempRoot "actionlint.zip"
        $url = "https://github.com/rhysd/actionlint/releases/download/v$version/actionlint_${version}_windows_$arch.zip"
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "actionlint archive SHA-256 mismatch: $actual" }
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tempRoot "bin")
        $ActionlintPath = Join-Path $tempRoot "bin\actionlint.exe"
    }

    & $ActionlintPath -color $workflow
    if ($LASTEXITCODE -ne 0) { throw "actionlint failed with exit code $LASTEXITCODE" }

    $contractPath = Join-Path $tempRoot "contract.py"
    [IO.File]::WriteAllText($contractPath, $contract, [Text.UTF8Encoding]::new($false))
    & $Python $contractPath $workflow
    if ($LASTEXITCODE -ne 0) { throw "PyYAML/contract fallback failed with exit code $LASTEXITCODE" }
}
catch {
    Write-Error $_
    if ($AllowContractFallback) {
        Write-Warning "actionlint unavailable or failed; running explicitly allowed PyYAML/contract fallback"
        $contractPath = Join-Path $tempRoot "contract.py"
        [IO.File]::WriteAllText($contractPath, $contract, [Text.UTF8Encoding]::new($false))
        & $Python $contractPath $workflow
        if ($LASTEXITCODE -ne 0) { exit 1 }
        exit 0
    }
    exit 1
}
finally {
    if ($tempRoot -and (Test-Path -LiteralPath $tempRoot)) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
