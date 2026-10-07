import subprocess
import sys
from pathlib import Path

from sion_ingestion.agent_bridge import PROVIDER_REGISTRY

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_agent_bridge.py"


def test_cli_exposes_every_registered_provider():
    out = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=True).stdout
    for name in PROVIDER_REGISTRY:
        assert name in out
