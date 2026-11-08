"""Configure ephemeral NVIDIA Auto Ontology CI model roles using an Actions secret.

Runner-only. Never run against production or print/write a key to workflow logs.
The source DB remains a fabricated read-only project-scoped PostgreSQL view.
"""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    if os.environ.get("GITHUB_REPOSITORY") != "khs0927/Ontology-platform":
        raise RuntimeError("refusing to configure outside the authorized CI repo")
    if os.environ.get("GITHUB_REF") != (
        "refs/heads/feat/nvidia-auto-ontology-federation-20261107"
    ):
        raise RuntimeError("refusing to configure outside the isolated CI branch")

    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key.startswith("nvapi-") or len(key) < 25:
        raise RuntimeError("NVIDIA Actions secret not present or badly formed")

    target = Path(os.environ["GITHUB_WORKSPACE"]) / "nvidia" / ".env"
    if not target.is_file():
        raise RuntimeError("run prepare_ephemeral_env.py before model setup")
    values = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            values[name] = value

    # No raw Sion DB, private drawing, customer document or production URL.
    if "sion_nvidia_ci" not in values.get("CONNECTION_STRINGS", ""):
        raise RuntimeError("only the disposable Sion source database is allowed")

    llm_url = "https://integrate.api.nvidia.com/v1"
    llm_id = "nvidia/nemotron-3.5-lightning-30b-a3b"
    emb_id = "nvidia/nemotron-3.5-embed-1b"
    rerank_id = "nvidia/nemotron-3.5-rerank-8b"

    for role in ("DEFAULT_MODELS", "REASONING", "NON_REASONING", "EMBED", "RERANK"):
        values[role + "_API_KEY"] = key
    for role in ("DEFAULT_MODELS", "REASONING", "NON_REASONING", "EMBED"):
        values[role + "_ENDPOINT"] = llm_url
    for role in ("DEFAULT_MODELS", "REASONING", "NON_REASONING"):
        values[role + "_MODEL"] = llm_id
    values["EMBED_MODEL"] = emb_id
    values["RERANK_MODEL"] = rerank_id
    values["RERANK_ENDPOINT"] = (
        "https://ai.api.nvidia.com/v1/retrieval/"
        "nvidia/nemotron-3.5-rerank-8b/reranking"
    )
    values["NVIDIA_API_KEY"] = key

    # The test's CI-only ingest/compile stack runs in isolated containers.
    # Updating this runner file does not alter any persistent credential store.
    content = "".join(f"{name}={value}\n" for name, value in values.items())
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)
    print("PASS ephemeral NIM model roles configured (credentials hidden)")
    print("Models: Nemotron Lightning chat, Nemotron 3.5 embed and rerank")


if __name__ == "__main__":
    main()
