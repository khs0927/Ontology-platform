# Bundle reproduction

This contract reproduces the repository at commit `715ea4c` from a complete Git bundle in a fresh temporary checkout. It does not use credentials, remotes, Docker, or EXE rebuilds. The default minimum clean-room gate is Fast; Full runs the complete pytest suite.

A bundle made from a shallow parent is not reproducible: a local clone can appear to work because the local object database supplies the missing parent. The reproduction gate therefore runs `git bundle verify` before clone, performs `git clone --no-local` without `--depth`, and rejects a shallow clean-room checkout.

## Create a full-history bundle

Create this only from a non-shallow repository or worktree. The helper refuses shallow sources and never overwrites an existing bundle. With no `-OutputBundle`, it writes a new file under the repository's `artifacts` directory.

```powershell
pwsh -File scripts/reproduce-from-bundle.ps1 `
  -SourceRepo C:\path\to\full-history-worktree `
  -Branch codex/p0-remediation-20260924
```

To choose the output path explicitly:

```powershell
pwsh -File scripts/reproduce-from-bundle.ps1 `
  -SourceRepo C:\path\to\full-history-worktree `
  -Branch codex/p0-remediation-20260924 `
  -OutputBundle C:\path\to\artifacts\full-bundle.bundle
```

If the source is shallow, first populate that source worktree from an approved local or remote source. The helper intentionally does not add a remote or fetch credentials. Do not point it at the broken shallow checkout.

## Verify and reproduce a bundle

```powershell
pwsh -File scripts/reproduce-from-bundle.ps1 `
  -BundlePath C:\path\to\full-bundle.bundle `
  -ExpectedCommit 715ea4c `
  -TestMode Fast
```

Use `-TestMode Full` for the complete test suite. Use `-SkipPackaging` only when the packaging gate is not needed. Verification runs inside a newly initialized empty repository, so local objects cannot mask a missing prerequisite. Verification fails before the temporary clone when the bundle reports a missing prerequisite or parent. A successful run clones the bundle through the bundle transport into a unique temporary directory, proves the checkout is not shallow, creates a virtual environment, installs the editable test extra, checks HEAD, branch and status, runs pytest, compiles Python sources, runs `pip check`, verifies the release lock, and then builds and clean-installs a wheel unless packaging is explicitly skipped. Docker and EXE rebuilds are not repeated because they were already verified.

The temporary checkout and virtual environments are removed in a `finally` block. The script has no remote configuration, credential, commit, or push operations.
