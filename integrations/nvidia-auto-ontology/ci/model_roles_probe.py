"""NVIDIA embed/rerank role compatibility smoke. Synthetic text only.

Source schemas/payloads are pinned to NVIDIA/auto-ontology:
auto_ontology/utils/embedding.py and auto_ontology/utils/rerank.py.
This script does not log API keys, inference outputs, vectors or passages.
"""
from __future__ import annotations

import json
import math
import os
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"
EMBED_MODEL = "nvidia/nemotron-3.5-embed-1b"
RERANK_URL = "https://ai.api.nvidia.com/v1/retrieval/nvidia/nemotron-3.5-rerank-8b/reranking"
RERANK_MODEL = "nvidia/nemotron-3.5-rerank-8b"
PASSAGE = "Door-101 belongs to Project A. Relation PART_OF is human verified."
NEGATIVE = "Green apples are harvested in orchards."
QUERY = "Which project contains Door-101?"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def report(message: str):
    print(message, flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as file:
            file.write(message.replace("|", "\\|") + "\n")


def request_payload(opener, url: str, key: str, body: dict) -> dict:
    req = Request(
        url,
        method="POST",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": "sion-nim-roles-synthetic-ci/1.0"},
    )
    with opener.open(req, timeout=45) as response:
        raw = response.read(400_001)
        if len(raw) > 400_000:
            raise ValueError("response size limit")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("expected a response object")
        return decoded


def check_embedding(payload: dict) -> tuple[int, list[float]]:
    if payload.get("model") and not isinstance(payload["model"], str):
        raise ValueError("invalid model metadata")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError("expected exactly two embeddings")
    rows = sorted(rows, key=lambda r: r["index"])
    if [row.get("index") for row in rows] != [0, 1]:
        raise ValueError("embedding indices mismatched")
    arrays = [row.get("embedding") for row in rows]
    if any(not isinstance(v, list) or not v or len(v) > 8192 for v in arrays):
        raise ValueError("missing/oversized embedding vector")
    if len(arrays[0]) != len(arrays[1]):
        raise ValueError("embedding dimensions inconsistent")
    for vec in arrays:
        if not all(type(v) in (int, float) and math.isfinite(v) for v in vec):
            raise ValueError("invalid embedding component")
    return len(arrays[0]), arrays[0]


def check_rerank(payload: dict) -> tuple[int, float]:
    items = payload.get("rankings")
    if not isinstance(items, list) or len(items) < 2:
        raise ValueError("expected both ranking entries")
    scores = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid ranking entry")
        idx, logit = item.get("index"), item.get("logit")
        if type(idx) is int and idx in (0, 1) and type(logit) in (int, float):
            scores[idx] = float(logit)
    if len(scores) != 2 or not all(math.isfinite(v) for v in scores.values()):
        raise ValueError("missing/invalid rerank scores")
    # Large positive means the correct synthetic source beat unrelated text.
    return (0 if scores[0] > scores[1] else 1), scores[0] - scores[1]


def offline() -> None:
    assert check_embedding({"data": [
        {"index": 1, "embedding": [0.1, 0.2]},
        {"index": 0, "embedding": [0.2, 0.1]},
    ]})[0] == 2
    assert check_rerank({"rankings": [{"index": 1, "logit": -1},
                                     {"index": 0, "logit": 2}]})[0] == 0
    for body in ({"data": []}, {"data": [{"index": 0, "embedding": [3]}]}):
        try:
            check_embedding(body)
        except ValueError:
            pass
        else:
            raise AssertionError("incorrect embedding response accepted")
    report("PASS isolated embed/rerank response-contract tests")


def live() -> int:
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key.startswith("nvapi-"):
        report("FAIL: NVIDIA secret absent; no requests made")
        return 1
    if os.environ.get("GITHUB_REPOSITORY") != "khs0927/Ontology-platform":
        report("FAIL: repository authorization mismatch")
        return 1
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        embed = request_payload(opener, EMBED_URL, key, {
            "model": EMBED_MODEL, "input": [PASSAGE, NEGATIVE],
            "input_type": "passage", "truncate": "END",
            "modality": "text", "encoding_format": "float",
        })
        dims, _ = check_embedding(embed)
        report(f"PASS real NVIDIA embeddings: {EMBED_MODEL}; vectors=2, dimensions={dims}")
    except HTTPError as exc:
        report(f"FAIL embeddings endpoint HTTP {exc.code}; model output hidden")
        return 2
    except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
        report("FAIL embeddings: " + type(exc).__name__)
        return 2

    try:
        rerank = request_payload(opener, RERANK_URL, key, {
            "model": RERANK_MODEL,
            "query": {"text": QUERY},
            "passages": [{"text": PASSAGE}, {"text": NEGATIVE}],
            "truncate": "END",
        })
        top_index, margin = check_rerank(rerank)
        if top_index != 0:
            report("FAIL rerank: irrelevant synthetic passage ranked above matching passage")
            return 3
        report(f"PASS real NVIDIA reranking: {RERANK_MODEL}; best synthetic passage correct")
        report("PASS embed + rerank models, no real Sion content and no response vectors saved")
        return 0
    except HTTPError as exc:
        report(f"FAIL rerank endpoint HTTP {exc.code}; model output hidden")
        return 3
    except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
        report("FAIL rerank: " + type(exc).__name__)
        return 3


if __name__ == "__main__":
    offline()
    sys.exit(live() if "--live" in sys.argv else 0)
