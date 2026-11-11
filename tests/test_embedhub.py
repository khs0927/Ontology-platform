from __future__ import annotations

import json
import math
import os

import pytest
from sion_embedhub import Embedder, EmbedError, KeyPool, ModelSpec, agreement, default_registry, rrf
from sion_embedhub.bench import metrics, run
from sion_embedhub.cli import main as cli_main
from sion_embedhub.keys import _Slot
from sion_embedhub.store import ddl


def test_key_pool_discovers_dedups_and_hides_values():
    env = {"NVIDIA_API_KEY": "SECRET-1", "NVIDIA_API_KEY_1": "SECRET-2", "NVIDIA_API_KEY_2": "SECRET-1", "NVIDIA_API_KEY_4": "SECRET-3", "OTHER": "z"}
    pool = KeyPool.from_env("NVIDIA_API_KEY", env)
    assert len(pool) == 3 and "OTHER" not in pool.names
    assert "SECRET" not in repr(pool._slots)  # secret never in repr


def test_key_pool_allows_an_empty_environment_and_acquire_explains_it():
    """Discovery must not fail when no key is set: local commands run keyless (#106 follow-up A1)."""
    pool = KeyPool.from_env("NVIDIA_API_KEY", {})
    assert len(pool) == 0 and pool.names == []
    with pytest.raises(RuntimeError, match="no API keys found"):
        pool.acquire()


def test_key_pool_rotates_and_cools_down():
    t = [0.0]
    pool = KeyPool([_Slot("K1", "a"), _Slot("K2", "b")], clock=lambda: t[0])
    s1 = pool.acquire(); pool.report(s1, False, retry_after=30)
    assert {pool.acquire().name for _ in range(4)} == {"K2"}
    t[0] = 100
    assert {pool.acquire().name for _ in range(4)} == {"K1", "K2"}


def _fake(vec_for):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append(body)
        return 200, {"data": [{"index": i, "embedding": vec_for(x, body)} for i, x in enumerate(body["input"])]}
    return transport, calls


def test_embedder_sends_input_type_dimensions_and_normalises():
    spec = default_registry().get("nv-1b")
    tr, calls = _fake(lambda x, b: [3.0, 4.0] + [0.0] * (b.get("dimensions", 2048) - 2))
    e = Embedder(spec, KeyPool([_Slot("K", "x")]), tr)
    v = e.embed(["a"], "query", 1024)[0]
    assert calls[0]["input_type"] == "query" and calls[0]["dimensions"] == 1024
    assert len(v) == 1024 and math.isclose(sum(x * x for x in v), 1.0)
    with pytest.raises(ValueError):
        e.embed(["a"], "passage", 999)


def test_embedder_retries_transient_then_succeeds_and_gives_up():
    spec = default_registry().get("nv-1b")
    n = {"i": 0}

    def flaky(url, headers, body, timeout):
        n["i"] += 1
        if n["i"] < 3:
            return 500, {"message": "service inference failed"}
        return 200, {"data": [{"index": 0, "embedding": [1.0] * 2048}]}
    e = Embedder(spec, KeyPool([_Slot("K", "x")]), flaky, sleep=lambda s: None)
    assert len(e.embed(["a"])[0]) == 2048 and n["i"] == 3
    bad = Embedder(spec, KeyPool([_Slot("K", "x")]), lambda *a: (401, "no"), sleep=lambda s: None)
    with pytest.raises(EmbedError):
        bad.embed(["a"])


def test_embedder_rejects_wrong_dimension_response():
    spec = default_registry().get("nv-1b")
    e = Embedder(spec, KeyPool([_Slot("K", "x")]), lambda *a: (200, {"data": [{"index": 0, "embedding": [1.0] * 7}]}))
    with pytest.raises(EmbedError):
        e.embed(["a"])


def test_space_ids_differ_even_when_dim_equal():
    r = default_registry()
    assert r.get("nv-1b").space_id(1024) != r.get("bge-m3").space_id(1024)
    with pytest.raises(ValueError):
        r.get("bge-m3").space_id(2048)


def test_rrf_and_agreement():
    fused = rrf({"text": ["a", "b", "c"], "image": ["b", "a", "d"]})
    assert [i for i, _ in fused][:2] == ["a", "b"]
    assert agreement({"text": ["a", "b"], "image": ["a", "c"]})["verdict"] == "confirmed"
    assert agreement({"text": ["a", "b"], "image": ["b", "c"]})["verdict"] == "partial"
    assert agreement({"text": ["a"], "image": ["z"]})["verdict"] == "conflict"
    assert agreement({"text": ["a"]})["verdict"] == "single_source"


def test_bench_end_to_end_with_fake_embedders():
    reg = default_registry()
    words = ["wall", "door", "window"]

    def vec(x, body):
        return [1.0 if w in x else 0.0 for w in words] + [0.01] * 5
    spec = type(reg.get("bge-m3"))("t", "ollama", "t", 8, (8,))
    def tr(url, h, body, t):
        return 200, {"embeddings": [vec(x, body) for x in body["input"]]}
    e = Embedder(spec, None, tr)
    docs = [{"type": "doc", "id": w, "text": f"{w} detail"} for w in words]
    qs = [{"type": "query", "q": "door", "relevant": ["door"]}]
    rep = run({"t": e}, docs, qs)
    assert rep["models"]["t"]["recall@1"] == 1.0 and rep["rrf_fusion"]["mrr"] == 1.0
    assert metrics([["x", "y"]], [{"relevant": ["y"]}])["mrr"] == 0.5


def test_ddl_uses_halfvec_above_2000_dims():
    r = default_registry()
    assert "vector(1024)" in ddl(r.get("nv-1b"), 1024)
    assert "USING hnsw (embedding vector_cosine_ops)" in ddl(r.get("nv-1b"), 1024)
    assert "halfvec(2048)" in ddl(r.get("nv-8b"), 2048)
    assert "USING hnsw (embedding halfvec_cosine_ops)" in ddl(r.get("nv-8b"), 2048)
    assert "halfvec(4096)" in ddl(r.get("nv-8b"))


def test_ddl_skips_the_ann_index_above_the_pgvector_halfvec_limit():
    """halfvec HNSW tops out at 4000 dims; nv-8b's native 4096d space keeps the column, not the index."""
    r = default_registry()
    sql = ddl(r.get("nv-8b"))
    assert "halfvec(4096)" in sql
    assert "USING hnsw" not in sql
    assert "exact search" in sql and "4000" in sql  # the DDL says why the index is missing

    at_limit = ModelSpec("h4000", "nvidia", "custom/halfvec-4000", 4000, (4000,))
    over_limit = ModelSpec("h4096", "nvidia", "custom/halfvec-4096", 4096, (4096,))
    assert "USING hnsw (embedding halfvec_cosine_ops)" in ddl(at_limit)
    assert "USING hnsw" not in ddl(over_limit)


def _clear_nvidia_keys(monkeypatch) -> None:
    for name in [n for n in os.environ if n == "NVIDIA_API_KEY" or n.startswith("NVIDIA_API_KEY_")]:
        monkeypatch.delenv(name, raising=False)


def test_cli_models_lists_models_without_any_nvidia_key(monkeypatch, capsys):
    """`models` is discovery only: no key needed, key names simply come back empty (#106 follow-up A1)."""
    _clear_nvidia_keys(monkeypatch)
    assert cli_main(["models"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["nvidia_keys"] == []
    assert report["models"]["nv-8b"]["dims"] == [4096, 2048, 1024, 512]


def test_cli_bench_of_a_local_model_never_builds_the_nvidia_pool(monkeypatch, tmp_path):
    """bge-m3 is local (Ollama): a missing NVIDIA key must not abort the benchmark (#106 follow-up A1)."""
    import sion_embedhub.cli as cli

    dataset = tmp_path / "ds.jsonl"
    dataset.write_text('{"type":"doc","id":"d1","text":"벽"}\n{"type":"query","q":"벽","relevant":["d1"]}\n',
                       encoding="utf-8")

    class _FakeEmbedder:
        def __init__(self, spec, pool=None):
            assert spec.provider != "nvidia"
            self.spec, self.pool = spec, pool

        def embed(self, items, role="passage", dim=None):
            d = dim or self.spec.native_dim
            return [[1.0] + [0.0] * (d - 1) for _ in items]

    def _boom(cls, *args, **kwargs):
        raise AssertionError("the NVIDIA KeyPool must only be built when an NVIDIA model is invoked")

    monkeypatch.setattr(cli, "Embedder", _FakeEmbedder)
    monkeypatch.setattr(cli.KeyPool, "from_env", classmethod(_boom))
    assert cli.main(["bench", str(dataset), "--models", "bge-m3"]) == 0


def test_embedder_halves_batch_when_service_rejects_large_batches():
    spec = default_registry().get("nv-3-1b")  # max_batch 32, but fake service only accepts <= 2

    def picky(url, headers, body, timeout):
        if len(body["input"]) > 2:
            return 500, {"message": "service inference failed"}
        return 200, {"data": [{"index": i, "embedding": [1.0] * 2048} for i in range(len(body["input"]))]}
    e = Embedder(spec, KeyPool([_Slot("K", "x")]), picky, retries=1, sleep=lambda s: None)
    assert len(e.embed(["t"] * 7)) == 7


def test_embedder_splits_batches_only_for_retryable_failures():
    """A 401/400 is not a batch-size problem: surface it at once instead of retrying each half (#106 A2)."""
    spec = default_registry().get("nv-3-1b")
    calls: list[int] = []

    def unauthorised(url, headers, body, timeout):
        calls.append(len(body["input"]))
        return 401, {"detail": "unauthorized"}

    e = Embedder(spec, KeyPool([_Slot("K", "x")]), unauthorised, retries=1, sleep=lambda s: None)
    with pytest.raises(EmbedError) as excinfo:
        e.embed(["t"] * 4)
    assert calls == [4]  # one request, no halving and no retry
    assert excinfo.value.status == 401

    def invalid(url, headers, body, timeout):
        calls.append(len(body["input"]))
        return 400, {"error": "invalid input"}

    e2 = Embedder(spec, KeyPool([_Slot("K", "x")]), invalid, retries=1, sleep=lambda s: None)
    with pytest.raises(EmbedError) as excinfo2:
        e2.embed(["t"] * 2)
    assert calls == [4, 2] and excinfo2.value.status == 400


def test_embedder_splits_a_payload_too_large_batch():
    spec = default_registry().get("nv-3-1b")
    seen: list[int] = []

    def too_large(url, headers, body, timeout):
        seen.append(len(body["input"]))
        if len(body["input"]) > 2:
            return 413, "payload too large"
        return 200, {"data": [{"index": i, "embedding": [1.0] * 2048} for i in range(len(body["input"]))]}

    e = Embedder(spec, KeyPool([_Slot("K", "x")]), too_large, retries=1, sleep=lambda s: None)
    assert len(e.embed(["t"] * 5)) == 5
    assert seen == [5, 2, 3, 1, 2]  # 413 halves the batch until every chunk fits


def test_embedder_without_an_nvidia_key_says_so_at_invocation():
    spec = default_registry().get("nv-1b")
    e = Embedder(spec, KeyPool([]))
    with pytest.raises(EmbedError, match="NVIDIA_API_KEY"):
        e.embed(["a"])
    assert e.embed([], "query") == []  # nothing to embed: no invocation, no error


def test_lightrag_adapter_uses_passage_by_default_and_query_inside_as_query():
    import asyncio

    pytest.importorskip("numpy")
    from sion_embedhub.lightrag import as_query, lightrag_embedding_func

    spec = default_registry().get("nv-1b")
    tr, calls = _fake(lambda x, b: [1.0] + [0.0] * (b.get("dimensions", 2048) - 1))
    fn = lightrag_embedding_func(Embedder(spec, KeyPool([_Slot("K", "x")]), tr), 1024)

    async def go():
        a = await fn(["doc"])
        with as_query():
            b = await fn(["q"])
        return a, b

    a, b = asyncio.run(go())
    assert a.shape == (1, 1024) and b.shape == (1, 1024)
    assert [c["input_type"] for c in calls] == ["passage", "query"]
