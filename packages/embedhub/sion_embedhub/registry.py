"""Embedding model registry.

Vectors from different models live in different spaces, so every spec carries a
stable ``space_id`` (model + dimension). Anything stored must be tagged with it and
only ever compared with vectors that share it. Same dimension != same space.

Specs were probed live against the NVIDIA API on 2026-11-06 (see docs/EMBEDHUB.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    key: str                      # short handle used in configs
    provider: str                 # "nvidia" | "ollama"
    model: str                    # provider model id
    native_dim: int
    dims: tuple[int, ...]         # dimensions the model can emit (matryoshka or fixed)
    modalities: tuple[str, ...] = ("text",)
    asymmetric: bool = False      # requires input_type query/passage
    max_batch: int = 32
    note: str = ""

    def space_id(self, dim: int | None = None) -> str:
        d = dim or self.native_dim
        if d not in self.dims:
            raise ValueError(f"{self.key}: dim {d} not in {self.dims}")
        slug = re.sub(r"[^a-z0-9]+", "_", self.model.lower()).strip("_")
        return f"{slug}_{d}d"

    def table_suffix(self, dim: int | None = None) -> str:
        return self.space_id(dim)


@dataclass
class Registry:
    specs: dict[str, ModelSpec] = field(default_factory=dict)

    def add(self, spec: ModelSpec) -> None:
        self.specs[spec.key] = spec

    def get(self, key: str) -> ModelSpec:
        try:
            return self.specs[key]
        except KeyError:
            raise KeyError(f"unknown embedding model {key!r}; known: {sorted(self.specs)}") from None

    def with_modality(self, modality: str) -> list[ModelSpec]:
        return [s for s in self.specs.values() if modality in s.modalities]


def default_registry() -> Registry:
    r = Registry()
    r.add(ModelSpec("nv-1b", "nvidia", "nvidia/nemotron-3.5-embed-1b", 2048,
                    (2048, 1024, 512, 256), asymmetric=True, max_batch=2,
                    note="matryoshka; used by sion_graphrag at 1024d. Service returns 500 for batches > 2 (probed 2026-11-06)"))
    r.add(ModelSpec("nv-8b", "nvidia", "nvidia/nemotron-3.5-embed-8b", 4096,
                    (4096, 2048, 1024, 512), asymmetric=True, max_batch=2,
                    note="largest NVIDIA text model; same batch<=2 limit"))
    r.add(ModelSpec("nv-3-1b", "nvidia", "nvidia/nemotron-3-embed-1b", 2048,
                    (2048,), note="fixed 2048d, symmetric"))
    r.add(ModelSpec("nv-vl", "nvidia", "nvidia/llama-nemotron-embed-vl-1b-v2", 2048,
                    (2048, 1024, 512), modalities=("text", "image"), asymmetric=True,
                    max_batch=8, note="text+image in one space: drawing renders and text are comparable"))
    r.add(ModelSpec("bge-m3", "ollama", "bge-m3", 1024, (1024,),
                    note="local, free, offline; 8192 ctx; strong Korean"))
    return r
