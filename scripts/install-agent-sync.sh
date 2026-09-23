#!/usr/bin/env bash
# Automated Background Sync Task Installer for Linux / macOS
# Adds a user crontab entry running every 15 minutes.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="$(which python3 || which python)"
BRIDGE_SCRIPT="$SCRIPT_DIR/run_agent_bridge.py"

echo "[*] Configuring automated ontology sync cron job..."
echo "    - Python: $PYTHON_BIN"
echo "    - Script: $BRIDGE_SCRIPT"

CRON_JOB="*/15 * * * * cd \"$REPO_ROOT\" && \"$PYTHON_BIN\" \"$BRIDGE_SCRIPT\" >> \"$REPO_ROOT/runtime/sync.log\" 2>&1"

(crontab -l 2>/dev/null | grep -v "run_agent_bridge.py" ; echo "$CRON_JOB") | crontab -

echo "[+] Successfully registered cron job in crontab."
echo "[*] Running initial sync test..."
"$PYTHON_BIN" "$BRIDGE_SCRIPT"
echo "[+] All set! This computer will now automatically ingest and sync agent sessions."
