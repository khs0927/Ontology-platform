"""Create isolated CI-only NVIDIA config. Never run against production services.

All credentials are random and exist only within one ephemeral GitHub runner.
No NVIDIA inference provider is invoked; model endpoints point to dead loopback.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

NVIDIA_DIR = Path(os.environ["GITHUB_WORKSPACE"]) / "nvidia"

def main() -> None:
    values = {
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "15432",
        "POSTGRES_USER": "sion_owner",
        "POSTGRES_PASSWORD": secrets.token_hex(20),
        "POSTGRES_DATABASE": "auto_ontology",
        "CONNECTION_STRINGS": (
            "postgresql://nvidia_pilot_reader:ci_only_test_password_0101"
            "@postgres:5432/sion_nvidia_ci"
        ),
        "PGADMIN_EMAIL": "no-pgadmin@example.invalid",
        "PGADMIN_PASSWORD": secrets.token_hex(18),
        "DEFAULT_MODELS_ENDPOINT": "http://127.0.0.1:9/v1",
        "DEFAULT_MODELS_API_KEY": "disabled_no_paid_inference",
        "DEFAULT_MODELS_MODEL": "offline_ci_only",
        "REASONING_ENDPOINT": "http://127.0.0.1:9/v1",
        "REASONING_API_KEY": "disabled_no_paid_inference",
        "REASONING_MODEL": "offline_ci_only",
        "NON_REASONING_ENDPOINT": "http://127.0.0.1:9/v1",
        "NON_REASONING_API_KEY": "disabled_no_paid_inference",
        "NON_REASONING_MODEL": "offline_ci_only",
        "EMBED_ENDPOINT": "http://127.0.0.1:9/v1",
        "EMBED_API_KEY": "disabled_no_paid_inference",
        "EMBED_MODEL": "offline_ci_only",
        "RERANK_ENDPOINT": "http://127.0.0.1:9/v1",
        "RERANK_API_KEY": "disabled_no_paid_inference",
        "RERANK_MODEL": "offline_ci_only",
        "APP_URL": "http://localhost:3000",
        "PYTHON_API_URL": "http://auto-ontology:3001",
        "AUTO_ONTOLOGY_MCP_PUBLIC_URL": "http://localhost:3003",
        "AUTO_ONTOLOGY_ADMIN_EMAIL": "sion-ci-admin@example.invalid",
        "AUTO_ONTOLOGY_ADMIN_PASSWORD": secrets.token_hex(20),
        "AUTH_SECRET": secrets.token_hex(32),
        "INGEST_INTERVAL_HOURS": "999",
    }
    path = NVIDIA_DIR / ".env"
    path.write_text("".join(f"{key}={val}\n" for key, val in values.items()))
    path.chmod(0o600)
    print("CI-only NVIDIA environment prepared (credentials hidden, model endpoint disabled).")

if __name__ == "__main__":
    main()
