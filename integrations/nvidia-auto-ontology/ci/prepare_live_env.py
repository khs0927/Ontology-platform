"""CI-only real NIM configuration: source secrets -> ephemeral local .env.

No user data. Not a deployment. Never print or commit model key values.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

NVIDIA_DIR = Path(os.environ["GITHUB_WORKSPACE"]) / "nvidia"

def main() -> None:
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key.startswith("nvapi-") or len(key) < 25:
        raise SystemExit("FAIL: NVIDIA_API_KEY missing or invalid; no live stack started")
    file = NVIDIA_DIR / ".env"
    if not file.is_file():
        raise SystemExit("FAIL: runner-only environment missing")
    raw = dict(
        line.partition("=")[::2] for line in file.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    raw.update({
        "DEFAULT_MODELS_ENDPOINT": "https://integrate.api.nvidia.com/v1",
        "DEFAULT_MODELS_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "DEFAULT_MODELS_API_KEY": key,
        "REASONING_ENDPOINT": "https://integrate.api.nvidia.com/v1",
        "REASONING_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "REASONING_API_KEY": key,
        "NON_REASONING_ENDPOINT": "https://integrate.api.nvidia.com/v1",
        "NON_REASONING_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "NON_REASONING_API_KEY": key,
        "EMBED_ENDPOINT": "https://integrate.api.nvidia.com/v1",
        "EMBED_MODEL": "nvidia/nemotron-3-embed-1b",
        "EMBED_API_KEY": key,
        "RERANK_ENDPOINT": (
            "https://ai.api.nvidia.com/v1/retrieval/nvidia/"
            "nemotron-3.5-rerank-8b/reranking"
        ),
        "RERANK_MODEL": "nvidia/nemotron-3.5-rerank-8b",
        "RERANK_API_KEY": key,
        "SEMANTIC_LLM_MAX_INFLIGHT": "2",
        "NIM_HTTP_MAX_CONCURRENT": "2",
        "DB_PROBE_PROACTIVE": "true",
        "DB_PROBE_JOIN_PATH_CHECK": "true",
    })
    if any("\n" in value or "\r" in value or not value for value in raw.values()):
        raise SystemExit("FAIL: invalid environment value")
    file.write_text(
        "".join(f"{name}={value}\n" for name, value in raw.items()),
        encoding="utf-8",
    )
    file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print("PASS: ephemeral NVIDIA NIM roles configured; all credentials redacted")

if __name__ == "__main__":
    main()
