# Signing preflight

`scripts/preflight-signing.ps1` is a read-only release check. It inspects tracked files under `bin/` and executable candidates under `dist/*.exe`, recording only:

- absolute and repository-relative path
- file size and SHA-256 hash
- file and product version metadata
- Authenticode status and a boolean signed flag

It detects, without changing anything, whether `signtool`, the current-user certificate store, and Azure Trusted Signing environment variables are available. Environment values and certificate/signature identity fields are never copied into the reports.

Reports are written under `tmp/signing-preflight/` as `signing-preflight.json` and `signing-preflight.md`. The JSON includes an `unsigned_release_block`. The command exits `2` when any candidate is unsigned, untrusted, or unverifiable, or when no candidate is present; it exits `0` only when **every** discovered candidate reports Authenticode status `Valid`.

## Trust policy: `Valid` only

The preflight is fail-closed on trust, not merely on presence:

- `Valid` is the only accepted status. It is recorded in the report as `accepted_statuses`.
- Every other state is blocking, recorded in `blocked_statuses`: `NotSigned`, `NotTrusted`, `UnknownError`, `Unavailable`, and `HashMismatch`. A signature that is present but untrusted is **not** a signed release candidate.
- A missing file, or an unavailable or throwing `Get-AuthenticodeSignature`, is also a blocking state rather than an unknown pass.

This replaces the earlier behavior that treated any non-`NotSigned` status as signed. Only `Valid` unblocks distribution.

## Current recorded state

- The committed `bin/sion-agent-bridge.exe` and a freshly built `dist` EXE are both `NotSigned`.
- `signtool`, the usable certificate store, and Azure Trusted Signing are unavailable on this host.
- Result: `unsigned_release_block=true`, exit code `2`, and the EXE remains prohibited for distribution.
- Signing is an external blocker independent of the push state. The branch is still pre-push: the remediation branch has never been pushed (no upstream configured, absent from `git ls-remote --heads origin`), and the user-approved push and PR have not been performed.

This check does not sign, purchase, enroll, mutate certificates, or modify release artifacts. Run it explicitly before release. `signtool`/certificate-store/Azure Trusted Signing availability is informational only.
