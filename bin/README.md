# bin/

Build output only. `sion-agent-bridge.exe` is **not tracked in git** any more.

- Download a built Windows binary from
  [GitHub Releases](https://github.com/khs0927/Ontology-platform/releases)
  (asset `sion-agent-bridge.exe` plus `sion-agent-bridge.exe.sha256`).
- Or build it yourself on Windows:

  ```powershell
  python -m pip install -e . pyinstaller
  python scripts/build_exe.py          # -> bin\sion-agent-bridge.exe
  ```

The `Release agent bridge` workflow (`.github/workflows/release-agent-bridge.yml`)
builds the binary on `windows-latest` for every pull request that touches the
bridge sources (build + smoke test only) and attaches it to the GitHub Release
when a `v*` tag is pushed.

Older binaries remain in git history (commits before v0.2.0); they were not
purged because that requires a history rewrite and force push.
