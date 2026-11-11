"""Run the drawing-retrieval benchmark that already ships in ``packages/embedhub/bench``.

The corpus builder and the 28 labelled queries are unchanged. This module renders that
corpus and scores it. A live NVIDIA call is opt-in: without ``NVIDIA_API_KEY`` the
command renders and skips. ``--offline`` uses :class:`FakeEmbedder` so CI can exercise
the same render and ranking path. Fake scores are not NVIDIA results.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

from .bench import load_dataset, run

_BUILD = Path(__file__).resolve().parents[1] / "bench" / "build_drawings_dataset.py"

# nv-vl text and nv-vl image against the text-only nv-1b baseline. nv-8b and bge-m3
# stay available through ``--models`` (bge-m3 needs a local Ollama).
DEFAULT_MODELS = ("nv-1b:1024", "nv-vl:1024", "nv-vl@image:1024")


def build_drawing_corpus(out_dir: str | Path) -> Path:
    """Render the Korean sheets and write ``OUT_DIR/drawings.jsonl``. Renders are not committed."""
    out = Path(out_dir)
    spec = importlib.util.spec_from_file_location("sion_embedhub_build_drawings", _BUILD)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(_BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc = mod.main(str(out))
    if rc != 0:
        raise RuntimeError(f"build_drawings_dataset failed ({rc})")
    dataset = out / "drawings.jsonl"
    if not dataset.is_file():
        raise FileNotFoundError(dataset)
    return dataset


class _Modalities:
    def __init__(self, modalities: tuple[str, ...]):
        self.modalities = modalities


class FakeEmbedder:
    """Deterministic stand-in with nv-vl's call shape: text or image in, one vector out.

    Records every input so a test can prove the image run received rendered sheets and
    the text run did not. Vectors are a hash of the input, not a model.
    """

    def __init__(self):
        self.spec = _Modalities(("text", "image"))
        self.seen: list[tuple[str, str]] = []

    def embed(self, items, role: str = "passage", dim: int | None = None) -> list[list[float]]:
        width = int(dim or 32)
        vecs = []
        for item in items:
            self.seen.append((role, item))
            vecs.append(_hash_vec(item, width))
        return vecs


def _hash_vec(text: str, dim: int) -> list[float]:
    acc = [0.0] * dim
    raw = text.encode("utf-8", "replace")
    step = max(1, len(raw) // 4096)
    for i, byte in enumerate(raw[::step]):
        acc[(i * 131 + byte) % dim] += 1.0
    if not any(acc):
        acc[0] = 1.0
    norm = math.sqrt(sum(x * x for x in acc))
    return [x / norm for x in acc]


def index_stats(embedders) -> dict:
    stats = {}
    for name, emb in embedders.items():
        seen = getattr(emb, "seen", None)
        if not seen:
            continue
        passages = [item for role, item in seen if role == "passage"]
        stats[name] = {
            "passages": len(passages),
            "images": sum(isinstance(item, str) and item.startswith("data:image/") for item in passages),
        }
    return stats


def score_drawings(dataset: Path, embedders, dims=None) -> dict:
    docs, queries = load_dataset(dataset)
    report = run(embedders, docs, queries, dims, dataset.parent)
    report["docs"] = len(docs)
    report["queries"] = len(queries)
    indexed = index_stats(embedders)
    if indexed:
        report["indexed"] = indexed
    return report
