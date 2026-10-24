from aec_assets_mcp import server as s
def test_search_polyhaven_tree():
    assert any("tree" in (h["name"] or "").lower() or "plant" in " ".join(h["categories"]) for h in s.search_polyhaven("models", "tree"))
def test_search_ambientcg():
    assert s.search_ambientcg("bricks", limit=3)
def test_rq_escapes_backslash():
    assert s._rq(r"C:\a\b") == '"C:/a/b"'
