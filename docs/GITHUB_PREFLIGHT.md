# GitHub preflight

`scripts/preflight-github.ps1` performs a **read-only** preflight for the current checkout. It does not push, open or update pull requests, change branch protection, or alter any repository setting.

## Usage

```powershell
./scripts/preflight-github.ps1 `
  -RepoPath (Get-Location).Path `
  -ExpectedBranch codex/p0-remediation-20260924 `
  -ExpectedHead 715ea4c
```

Reports are written as timestamped JSON and Markdown files. The default destination is the session `tmp` directory when available; use `-OutputDirectory` to choose another local directory. Reports redact synthetic or observed bearer values, token/password fields, OAuth prefixes, URL query values, and email-like metadata before writing. The `gh auth status` check intentionally records only `authenticated` and its `exit_code`; its command, output, username, token prefix, and scopes are never persisted.

## Checks

- `git remote -v` and `git status --short --branch`
- current branch and exact HEAD
- `git ls-remote --heads origin` (read-only; use `-SkipRemote` when network access is prohibited)
- `gh auth status`, when the GitHub CLI is installed
- `gh repo view` for fork, viewer permission, and default branch when authenticated
- GitHub branch protection and check-runs API, when authentication and repository access permit

Remote API capabilities are reported as unavailable rather than guessed. The report includes expected and actual branch/HEAD, the remote URL when visible, and a statement that no mutation was performed. `gh auth status` is used only to determine whether authenticated API checks may run.

## Recorded state: submission

- Repository: `khs0927/Ontology-platform` (private), remote `origin` = `https://github.com/khs0927/Ontology-platform.git`.
- Local branch `codex/p0-remediation-20260924` at head `715ea4c0827b74328b5edf852be844472eaf7c96`.
- The branch is **absent from the remote**: `git ls-remote --heads origin` lists only `main` (`44c3ec0fa7972118964b24b0b9516fac598b86a4`) and unrelated `codex/*` branches, never the remediation branch. `git rev-parse --abbrev-ref --symbolic-full-name '@{u}'` fails with `fatal: no upstream configured`, so all P0/P1 work is local-only and has never been pushed.
- Branch protection on `main` is reported **false**, so no required-check enforcement exists. Do not infer enforcement from a workflow file.
- Hosted CI remains **billing-blocked**: GitHub-hosted Actions runs cannot execute, so there is no hosted job conclusion to record. Billing-blocked, cancelled, skipped, or absent runs are blocked, never successful CI.
- The user approved a push and PR, but **neither has been performed yet**. The current state is pre-push, and nothing has been committed, pushed, or opened. Re-run this preflight after the push and record the hosted run URL, commit SHA, and job conclusions.

## Verification

Run the contract tests from the repository root:

```powershell
python -m pytest tests/test_github_preflight_contract.py
```
