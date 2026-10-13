"""SketchUp class proposals, block decisions and level links reach /review as pending candidates."""

from __future__ import annotations

import json

from test_review_bulk import AUTH, ROOT, client

EXPORT = ROOT / "data" / "bootstrap" / "sketchup-0914-meeting.ontology.json"
PREDICATES = {"classified_as_supplement": 41, "collapsed_as_block": 26, "on_level": 158, "on_level_by_top": 2}


def test_sketchup_candidates_listed_pending_not_auto_approved():
    data = json.loads(EXPORT.read_text(encoding="utf-8"))
    c = client()
    r = c.post(
        "/api/v1/import/graph-export",
        json={
            "path": str(EXPORT),
            "expected_node_count": data["expected_node_count"],
            "expected_edge_count": data["expected_edge_count"],
        },
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    cands, offset = [], 0
    while True:
        body = c.get(f"/api/v1/relations/candidates?status=all&limit=1000&offset={offset}", headers=AUTH).json()
        assert body["counts"]["approved"] == 0
        cands += body["candidates"]
        offset += 1000
        if offset >= body["total"]:
            break
    got: dict[str, int] = {}
    assert all(x["status"] == "pending" for x in cands)
    sk = {
        (e["source_stable_key"], e["relation_type_id"], e["target_stable_key"]): e["properties"]["predicate"]
        for e in data["edges"]
    }
    for x in cands:
        p = sk.get((x["source"]["stable_key"], x["relation_type_id"], x["target"]["stable_key"]))
        if p in PREDICATES:
            got[p] = got.get(p, 0) + 1
    assert got == PREDICATES
