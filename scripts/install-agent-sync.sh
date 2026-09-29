#!/usr/bin/env bash
# Automated Background Sync Task Installer for Linux / macOS
# Installs one managed crontab block and never deletes unmanaged entries.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="$(command -v python3 || command -v python)"
BRIDGE_SCRIPT="$SCRIPT_DIR/run_agent_bridge.py"
MANAGED_BEGIN="# BEGIN sion-agent-sync managed"
MANAGED_END="# END sion-agent-sync managed"
WRAPPER="$REPO_ROOT/runtime/run-agent-sync.sh"
LOG_PATH="$REPO_ROOT/runtime/sync.log"
[ -f "$BRIDGE_SCRIPT" ] || { echo "Bridge script not found: $BRIDGE_SCRIPT" >&2; exit 1; }
mkdir -p "$REPO_ROOT/runtime"
cat > "$WRAPPER" <<'WRAPPER'
#!/bin/sh
set -eu
"$SION_PYTHON" - "$SION_BRIDGE" "$SION_LOG" <<'PY'
import subprocess
import sys

bridge, log_path = sys.argv[1:3]
with open(log_path, "ab", buffering=0) as log:
    try:
        completed = subprocess.run(
            [sys.executable, bridge],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(124)
raise SystemExit(completed.returncode)
PY
WRAPPER
chmod 700 "$WRAPPER"
# crontab invokes only the fixed wrapper; it never embeds command text or quotes paths.
CRON_LINE="*/15 * * * * SION_PYTHON=$(printf '%q' "$PYTHON_BIN") SION_BRIDGE=$(printf '%q' "$BRIDGE_SCRIPT") SION_LOG=$(printf '%q' "$LOG_PATH") $WRAPPER"
TMP_CRONTAB="$(mktemp)"
trap 'rm -f "$TMP_CRONTAB"' EXIT
(crontab -l 2>/dev/null | awk -v b="$MANAGED_BEGIN" -v e="$MANAGED_END" 'index($0,b)==0 && index($0,e)==0 && index($0,"runtime/run-agent-sync.sh")==0' || true) > "$TMP_CRONTAB"
printf '%s\n%s\n%s\n' "$MANAGED_BEGIN" "$CRON_LINE" "$MANAGED_END" >> "$TMP_CRONTAB"
crontab "$TMP_CRONTAB"
echo "[+] Successfully registered managed cron block."
echo "[*] Running initial sync test..."
set +e
"$PYTHON_BIN" "$BRIDGE_SCRIPT"
INITIAL_EXIT=$?
set -e
[ "$INITIAL_EXIT" -eq 0 ] || { echo "Initial sync failed with exit code $INITIAL_EXIT" >&2; exit "$INITIAL_EXIT"; }
echo "[+] All set! This computer will now automatically ingest and sync agent sessions."
