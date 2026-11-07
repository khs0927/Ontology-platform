"""Provider clients. stdlib only; the HTTP transport is injectable so tests never touch the network."""

from __future__ import annotations

import base64
import json
import math
import mimetypes
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from .keys import KeyPool
from .registry import ModelSpec

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/embeddings"
OLLAMA_URL = "http://127.0.0.1:11434/api/embed"

# transport(url, headers, body_dict, timeout) -> (status, parsed_json_or_text)
Transport = Callable[[str, dict, dict, float], tuple[int, object]]


class EmbedError(RuntimeError):
    pass


def urllib_transport(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, object]:
    req = urllib.request.Request(url, json.dumps(body).encode(), {**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:300]
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 599, str(e)[:200]


def image_to_data_url(path: str | Path) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def l2_normalize(v: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)


class Embedder:
    """embed(texts_or_images, role='passage'|'query', dim=None) -> list[list[float]] (L2-normalised)."""

    def __init__(self, spec: ModelSpec, pool: KeyPool | None = None, transport: Transport = urllib_transport,
                 retries: int = 5, timeout: float = 90.0, sleep=time.sleep, url: str | None = None):
        self.spec, self.pool, self.transport = spec, pool, transport
        self.retries, self.timeout, self._sleep = retries, timeout, sleep
        self.url = url or (NVIDIA_URL if spec.provider == "nvidia" else OLLAMA_URL)
        if spec.provider == "nvidia" and pool is None:
            raise ValueError("nvidia provider needs a KeyPool")

    def embed(self, items: Sequence[str], role: str = "passage", dim: int | None = None) -> list[list[float]]:
        if role not in ("passage", "query"):
            raise ValueError("role must be 'passage' or 'query'")
        dim = dim or self.spec.native_dim
        if dim not in self.spec.dims:
            raise ValueError(f"{self.spec.key}: dim {dim} not in {self.spec.dims}")
        out: list[list[float]] = []
        for i in range(0, len(items), self.spec.max_batch):
            out.extend(self._call_split(list(items[i:i + self.spec.max_batch]), role, dim))
        return out

    def _call_split(self, batch: list[str], role: str, dim: int) -> list[list[float]]:
        """Halve the batch when the service keeps rejecting it (observed: nemotron-3.5 returns 500 for batches > 2)."""
        try:
            return self._call(batch, role, dim)
        except EmbedError:
            if len(batch) == 1:
                raise
            mid = len(batch) // 2
            return self._call_split(batch[:mid], role, dim) + self._call_split(batch[mid:], role, dim)

    # --- internals -------------------------------------------------------
    def _call(self, batch: list[str], role: str, dim: int) -> list[list[float]]:
        last = ""
        for attempt in range(self.retries):
            slot = self.pool.acquire() if self.pool else None
            headers = {"Authorization": f"Bearer {slot.value}"} if slot else {}
            status, data = self.transport(self.url, headers, self._body(batch, role, dim), self.timeout)
            if status == 200:
                if slot:
                    self.pool.report(slot, True)
                return self._parse(data, dim, len(batch))
            last = f"{status} {str(data)[:160]}"
            retryable = status in (429, 500, 502, 503, 504, 599)
            if slot:
                # 429 -> cool this key down; 5xx "service inference failed" is transient server-side
                self.pool.report(slot, False, retry_after=30.0 if status == 429 else 2.0)
            if not retryable:
                break
            self._sleep(min(2 ** attempt * 0.5, 8.0))
        raise EmbedError(f"{self.spec.key}: embedding failed after retries: {last}")

    def _body(self, batch: list[str], role: str, dim: int) -> dict:
        s = self.spec
        if s.provider == "ollama":
            return {"model": s.model, "input": batch}
        body: dict = {"model": s.model, "input": batch, "truncate": "END", "encoding_format": "float"}
        if s.asymmetric:
            body["input_type"] = role
        if dim != s.native_dim:
            body["dimensions"] = dim
        return body

    def _parse(self, data, dim: int, n: int) -> list[list[float]]:
        if not isinstance(data, dict):
            raise EmbedError(f"{self.spec.key}: unexpected response {str(data)[:120]}")
        if self.spec.provider == "ollama":
            vecs = data.get("embeddings") or []
        else:
            vecs = [d["embedding"] for d in sorted(data.get("data", []), key=lambda d: d.get("index", 0))]
        if len(vecs) != n or any(len(v) != dim for v in vecs):
            raise EmbedError(f"{self.spec.key}: got {len(vecs)} vectors of dim {len(vecs[0]) if vecs else '?'}, wanted {n}x{dim}")
        return [l2_normalize(v) for v in vecs]
