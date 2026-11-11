"""Multi-model embedding framework: registry, key pool, providers, rank fusion, benchmark."""

from .fusion import agreement, rrf
from .keys import KeyPool
from .providers import Embedder, EmbedError, image_to_data_url
from .registry import ModelSpec, Registry, default_registry

__all__ = ["Embedder", "EmbedError", "KeyPool", "ModelSpec", "Registry", "agreement",
           "default_registry", "image_to_data_url", "rrf"]
