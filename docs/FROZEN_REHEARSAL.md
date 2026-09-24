# Frozen EXE rehearsal

This rehearsal is intentionally performed from a fresh temporary virtual environment. The committed `bin` executable is not modified or used as the artifact under test; the executable under test is `dist/sion-agent-bridge.exe` produced by `scripts/build_exe.py`.

## Required checks

1. `dist/sion-agent-bridge.exe --help` exits zero and prints the bridge CLI help.
2. `SION_DATA_ROOT=<external writable directory> dist/sion-agent-bridge.exe --dry-run` exits according to the provider-discovery result, does not persist outputs, and never uses `_MEIPASS` as the data root.
3. The PyInstaller archive contains actual payloads under `sion_api/resources/`, not merely package names.
4. Qualified imports such as `sion_ingestion.bridge_cli` are present and executable.
5. `tests/test_frozen_contract.py` passes with the archive inspection enabled.

## Result policy

Any failed or skipped required check is a contract failure. Record the exact command, exit code, and blocker below rather than weakening the contract. No commit or push is part of this rehearsal.

## Rehearsal record

- Working tree: `C:\Users\khs09\.aside\u\0\sessions\2026-09-24_jUqcSVs0dQF6IcPX\tmp\Ontology-platform-review`
- Temporary venv: `rehearsal-venv-20260924` (Python 3.13.12, PyInstaller 6.22.3)
- Build command: `python scripts/build_exe.py --data-root C:\Users\khs09\.aside\u\0\sessions\2026-09-24_jUqcSVs0dQF6IcPX\tmp\rehearsal-data-20260924`
- Build result: PASS, exit 0. `dist\sion-agent-bridge.exe` was generated; committed `bin` was not modified.
- Help result: PASS, exit 0.
- Dry-run result: PASS for no-persist boundary, exit 1 because the selected Claude session was DLP-blocked (`1 finding`); the configured external root remained empty. This is a contract-valid blocked payload, not a persistence failure.
- Archive result: PASS, exit 0. Actual payload entries were present for `sion-core.yaml`, `sion-core.shacl.ttl`, `current-map-inventory.json`, and `map-export.example.json` under `sion_api/resources`; qualified entry point was exercised by the EXE help command.
- Contract test result: PASS, `8 passed`, with archive inspection enabled.
- Initial blockers fixed: PyInstaller rejects `--upx/--noupx` when a `.spec` is supplied, and the environment's `PIP_PREFIX` initially installed packages outside the fresh venv. The build script no longer passes those invalid flags; the retry used a fresh venv with `PIP_PREFIX` cleared.
- Remaining blocker: no persistence artifact or qualified-import blocker observed. Dry-run returns 1 for DLP-blocked input by design; document this exact outcome rather than forcing a zero exit.

The source resource set is `apps/api/sion_api/resources/*`; PyInstaller preserved its payload bytes in the frozen archive.
