# Security and privacy

Report security problems through GitHub's private vulnerability reporting rather than a public issue.
Include affected versions and steps to reproduce. Keep credentials and personal data out of reports.

Keep this local-first platform on loopback unless bearer authentication is configured.
Set `SION_API_AUTH_MODE=bearer` and scoped `SION_API_TOKENS_JSON` for remote Sion deployments.
Set `AEC_API_TOKEN` for remote operational AEC deployments. Token-free access is restricted to
loopback peers with trusted Host and Origin headers. Use TLS at the deployment proxy.
Allow remote browser origins explicitly with `SION_CORS_ORIGINS` or `AEC_CORS_ORIGINS`.
Configure ingestion roots to limit server-side file access.

Agent transcripts, runtime databases, private graph exports, credentials, personal email addresses,
profile paths and private Google Drive identifiers must stay outside the public repository.
Use environment variables for installation paths and Drive configuration.
The public examples contain redacted Drive identifiers; configure your own before use.

Run `python scripts/check_public_privacy.py` before publishing. CI repeats this check and audits the
locked dependencies. GitHub secret scanning and push protection are enabled for this repository.
