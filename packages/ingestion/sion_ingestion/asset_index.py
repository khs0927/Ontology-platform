"""SketchUp BIM asset cards (``sion-bim-asset/1``) -> hybrid search index + Graph RAG retrieval.

One read-only SQLite file holds:

* ``node`` / ``edge``: knowledge graph. Node kinds ``asset`` (definition or instance card),
  ``class``, ``ifc``, ``material``, ``level``, ``recipe``, ``tag``, ``model``. Edge rels
  ``instance_of`` (instance -> definition), ``in_class``, ``maps_to_ifc``, ``uses_material``,
  ``on_level``, ``made_by`` (asset/class -> recipe), ``contains`` (parent -> child),
  ``tagged``, ``in_model``.
* ``search_fts`` (FTS5 unicode61) and ``search_tri`` (FTS5 trigram, Korean substrings).
* ``node_vec``: float32 vectors. A local OpenAI-compatible embedding endpoint (for example
  text-embeddings-inference serving ``BAAI/bge-m3``) is used when ``SION_ASSET_EMBED_URL`` is
  set and points at a local/private host; otherwise a deterministic character n-gram hash
  embedder (labelled ``hash-chargram-384-v1``) is used. Vectors from different models are never
  compared: the query is embedded with the model recorded in ``meta``.
* ``meta``: schema, embedding model, counts, source card digests (no build timestamp, so the
  manifest is reproducible).

Queries fuse BM25, trigram, vector and dimension matches with Reciprocal Rank Fusion, then expand
1-2 graph hops (recipe, materials, IFC mapping, level, definition, children) as ``context``.

Standard library only. The index is derived data: rebuild it from the cards, never hand-edit.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import sqlite3
import sys
import urllib.request
from array import array
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

SCHEMA = "sion-bim-asset-index/1"
CARD_SCHEMA = "sion-bim-asset/1"
HASH_MODEL = "hash-chargram-384-v1"
HASH_DIM = 384
DEFAULT_INDEX_NAME = "sketchup-assets.sqlite"
RRF_K = 60

# class -> Korean/English search words (the cheapest quality lever).
LEXICON: dict[str, list[str]] = {
    "annotation": ["주석", "치수", "문자", "annotation", "dimension", "text"],
    "beam": ["보", "큰보", "작은보", "철골보", "beam", "girder"],
    "building": ["건물", "매스", "건물매스", "동", "별동", "본관", "building", "mass"],
    "cad-reference": ["캐드", "도면", "참조", "dwg", "cad"],
    "column": ["기둥", "철골기둥", "column", "pillar", "post"],
    "counter-millwork": ["카운터", "수납", "가구장", "주방", "바", "counter", "cabinet", "millwork"],
    "curtain-wall": ["커튼월", "유리벽", "유리커튼월", "멀리언", "curtain wall", "glazing", "mullion"],
    "door": ["문", "출입문", "도어", "door"],
    "exterior-stair": ["외부계단", "계단", "옥외계단", "stair", "exterior stair"],
    "floor-slab": ["슬래브", "바닥", "바닥판", "slab", "floor"],
    "furniture": ["가구", "의자", "테이블", "탁자", "소파", "카페", "좌석", "furniture", "chair", "table", "seat"],
    "glass-railing": ["유리난간", "난간", "강화유리", "glass railing", "balustrade", "guard"],
    "handrail": ["핸드레일", "난간", "손잡이", "handrail", "railing"],
    "imported-3d": ["가져온", "외부모델", "3d", "imported"],
    "interior-stair": ["내부계단", "실내계단", "계단", "stair", "interior stair"],
    "marker": ["마커", "표식", "marker"],
    "parking-deck": ["주차데크", "주차장", "경사로", "램프", "parking deck", "ramp"],
    "parking-stall": ["주차면", "주차칸", "주차", "parking stall", "parking space"],
    "paving": ["포장", "보도", "바닥포장", "paving", "pavement"],
    "person": ["사람", "인물", "점경", "person", "people", "human"],
    "planter": ["플랜터", "화분", "화단", "planter"],
    "retaining-wall": ["옹벽", "토목벽", "retaining wall"],
    "road-plan-surface": ["도로", "도로계획", "road"],
    "roof": ["지붕", "평지붕", "처마", "roof", "eave"],
    "site-container": ["대지", "부지", "사이트", "site"],
    "terrain": ["지형", "땅", "경사지", "대지", "terrain", "topography"],
    "tree": ["나무", "수목", "조경", "tree", "landscape"],
    "unused-definition": ["미사용", "안쓰는", "unused"],
    "wall": ["벽", "벽체", "외벽", "내벽", "wall"],
    "window-louver": ["창", "창문", "창호", "루버", "window", "louver"],
    "window": ["창", "창문", "창호", "미서기", "고창", "띠창", "window", "sliding window"],
    "fire-entry-window": ["소방관진입창", "소방관 진입창", "진입창", "소방", "역삼각형", "fire entry window", "firefighter window"],
    "louver": ["루버", "차양", "살", "louver", "louvre", "shading"],
}

_DIM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|cm|m)\b", re.I)
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣._#-]+")


# ---------------------------------------------------------------- embeddings
def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


class HashEmbedder:
    """Deterministic offline embedder: hashed character 1-3 grams + word tokens, L2-normalized."""

    model = HASH_MODEL
    dim = HASH_DIM

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        low = text.lower()
        feats: list[str] = [f"w:{w}" for w in _TOKEN_RE.findall(low)]
        for word in _TOKEN_RE.findall(low):
            padded = f" {word} "
            for n in (2, 3):
                feats.extend(f"c{n}:{padded[i:i + n]}" for i in range(len(padded) - n + 1))
        for f in feats or [low]:
            h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            vec[idx] += 1.0 if h[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class LocalEndpointEmbedder:
    """OpenAI-compatible ``/v1/embeddings`` on a local host (e.g. TEI serving BAAI/bge-m3)."""

    def __init__(self, url: str, model: str, timeout: float = 60.0):
        if not _is_local_url(url):
            raise ValueError("SION_ASSET_EMBED_URL must point at a local or private host")
        self.url = url.rstrip("/")
        if not self.url.endswith("/embeddings"):
            self.url += "/v1/embeddings"
        self.model = model
        self.timeout = timeout
        self.dim = 0

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 32):
            body = json.dumps({"model": self.model, "input": texts[i:i + 32]}).encode()
            req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - local only
                data = json.loads(resp.read())
            rows = sorted(data["data"], key=lambda r: r.get("index", 0))
            for r in rows:
                v = [float(x) for x in r["embedding"]]
                n = math.sqrt(sum(x * x for x in v))
                if not n or not all(math.isfinite(x) for x in v):
                    raise RuntimeError("embedding endpoint returned an unusable vector")
                out.append([x / n for x in v])
        if len(out) != len(texts):
            raise RuntimeError("embedding endpoint returned the wrong number of vectors")
        self.dim = len(out[0]) if out else self.dim
        return out


def make_embedder(model: str | None = None):
    url = os.getenv("SION_ASSET_EMBED_URL")
    if model == HASH_MODEL or not url:
        return HashEmbedder()
    return LocalEndpointEmbedder(url, model or os.getenv("SION_ASSET_EMBED_MODEL", "BAAI/bge-m3"))


def _pack(v: list[float]) -> bytes:
    return array("f", v).tobytes()


def _unpack(b: bytes) -> array:
    a = array("f")
    a.frombytes(b)
    return a


# ---------------------------------------------------------------- cards
def iter_cards(roots: Iterable[Path]) -> Iterable[tuple[Path, dict[str, Any]]]:
    """Yield ``(source_file, card)`` from ``<root>/<model>/cards.jsonl`` (or ``cards/*.json``)."""
    for root in roots:
        root = Path(root)
        jsonls = sorted(root.glob("*/cards.jsonl")) + ([root / "cards.jsonl"] if (root / "cards.jsonl").exists() else [])
        seen_dirs = set()
        for jl in jsonls:
            seen_dirs.add(jl.parent)
            with jl.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield jl, json.loads(line)
        for d in sorted(p for p in root.glob("*/cards") if p.is_dir() and p.parent not in seen_dirs):
            for f in sorted(d.glob("*.json")):
                yield f, json.loads(f.read_text(encoding="utf-8"))


def load_recipes(recipe_dir: Path | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if recipe_dir and Path(recipe_dir).is_dir():
        for f in sorted(Path(recipe_dir).glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            out[data.get("class") or f.stem] = {"path": f.as_posix(), "data": data}
    return out


def _card_name(card: dict[str, Any]) -> str:
    src = card.get("source") or {}
    return src.get("name") or src.get("definition") or card["asset_id"]


def card_text(card: dict[str, Any]) -> str:
    src = card.get("source") or {}
    cls = card.get("class") or ""
    ifc = card.get("ifc") or {}
    lvl = card.get("level") or {}
    tag = card.get("tag") or {}
    rec = card.get("recipe") or {}
    p = card.get("parameters") or {}
    parts = [
        _card_name(card), src.get("definition") or "", src.get("path") or "", cls,
        " ".join(LEXICON.get(cls, [])), ifc.get("entity") or "", ifc.get("predefined_type") or "",
        lvl.get("name") or "", " ".join(tag.get("current") or []), tag.get("proposed_zium") or "",
        rec.get("method") or "", rec.get("method_ko") or "", card.get("basis_ko") or "",
        " ".join(m.get("sketchup_material") or "" for m in card.get("materials") or []),
        " ".join(m.get("bim_material_category") or "" for m in card.get("materials") or []),
        "블럭 block" if card.get("block") else "",
    ]
    op = card.get("opening") or {}
    if op:
        g = op.get("geometry") or {}
        parts += [op.get("type_code") or "", op.get("role") or "", op.get("orientation") or "",
                  g.get("operation_type") or "", g.get("panel_layout") or "", op.get("note_ko") or "",
                  (op.get("compliance") or {}).get("status") or ""]
        if g.get("width_mm") and g.get("height_mm"):
            parts.append(f"{g['width_mm']}x{g['height_mm']} W{g['width_mm']} H{g['height_mm']}")
    for k in ("height_mm", "length_mm", "width_mm", "thickness_mm"):
        if isinstance(p.get(k), (int, float)):
            parts.append(f"{k}={round(p[k])}mm {round(p[k] / 1000, 2)}m")
    return " ".join(x for x in parts if x)


# ---------------------------------------------------------------- build
DDL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE node(id TEXT PRIMARY KEY, kind TEXT, key TEXT, label TEXT, props_json TEXT);
CREATE TABLE edge(src TEXT, rel TEXT, dst TEXT, weight REAL DEFAULT 1, evidence TEXT);
CREATE INDEX edge_src ON edge(src); CREATE INDEX edge_dst ON edge(dst);
CREATE TABLE asset(id TEXT PRIMARY KEY, model TEXT, card_kind TEXT, class TEXT, ifc_entity TEXT,
  block INTEGER, inside_block INTEGER, confidence REAL, review_state TEXT, level TEXT,
  height_mm REAL, length_mm REAL, width_mm REAL, thickness_mm REAL,
  asset_root TEXT, skp_path TEXT, thumb_path TEXT, sha256 TEXT, card_path TEXT, text TEXT);
CREATE VIRTUAL TABLE search_fts USING fts5(id UNINDEXED, text, tokenize="unicode61 tokenchars '.-#'");
CREATE VIRTUAL TABLE search_tri USING fts5(id UNINDEXED, text, tokenize='trigram');
CREATE TABLE node_vec(id TEXT PRIMARY KEY, vec BLOB);
"""


def build_index(card_roots: list[Path], out_path: Path, *, recipe_dir: Path | None = None,
                embed: bool = True, embedder=None, base: Path | None = None) -> dict[str, Any]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(DDL)
    recipes = load_recipes(recipe_dir)

    def rel(p: Path | str) -> str:
        p = Path(p)
        if base:
            try:
                return p.resolve().relative_to(Path(base).resolve()).as_posix()
            except ValueError:
                pass
        return p.as_posix()

    nodes: dict[str, tuple] = {}
    edges: set[tuple] = set()

    def node(nid: str, kind: str, key: str, label: str, props: dict | None = None) -> str:
        if nid not in nodes:
            nodes[nid] = (nid, kind, key, label, json.dumps(props or {}, ensure_ascii=False, sort_keys=True))
        return nid

    cards = list(iter_cards(card_roots))
    digest = hashlib.sha256()
    by_pid: dict[tuple[str, int], str] = {}
    def_by_name: dict[tuple[str, str], str] = {}
    for _, c in cards:
        if c.get("schema") not in (None, CARD_SCHEMA):
            continue
        src = c.get("source") or {}
        if c.get("card_kind") == "instance" and src.get("pid") is not None:
            by_pid[(c["model"], src["pid"])] = c["asset_id"]
        if c.get("card_kind") == "definition" and src.get("definition"):
            def_by_name[(c["model"], src["definition"])] = c["asset_id"]

    texts: dict[str, str] = {}
    for path, c in cards:
        if c.get("schema") not in (None, CARD_SCHEMA):
            continue
        digest.update(json.dumps(c, sort_keys=True, ensure_ascii=False).encode())
        aid, model, cls = c["asset_id"], c.get("model") or "", c.get("class") or "unclassified"
        src, ifc, lvl = c.get("source") or {}, c.get("ifc") or {}, c.get("level") or {}
        af, p, rec = c.get("asset_file") or {}, c.get("parameters") or {}, c.get("recipe") or {}
        text = card_text(c)
        texts[aid] = text
        ev = rel(path)
        node(aid, "asset", aid, _card_name(c), {"card_kind": c.get("card_kind"), "model": model,
             "review_state": c.get("review_state"), "confidence": c.get("confidence")})
        con.execute("INSERT OR REPLACE INTO asset VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            aid, model, c.get("card_kind"), cls, ifc.get("entity"), int(bool(c.get("block"))),
            int(bool(c.get("inside_block"))), c.get("confidence"), c.get("review_state"), lvl.get("name"),
            p.get("height_mm"), p.get("length_mm"), p.get("width_mm"), p.get("thickness_mm"),
            af.get("root"), af.get("skp"), af.get("thumbnail"), af.get("sha256"), ev, text))
        edges.add((aid, "in_model", node(f"model:{model}", "model", model, model), 1.0, ev))
        edges.add((aid, "in_class", node(f"class:{cls}", "class", cls, cls, {"lexicon": LEXICON.get(cls, [])}), 1.0, ev))
        if ifc.get("entity"):
            iid = f"ifc:{ifc['entity']}" + (f".{ifc['predefined_type']}" if ifc.get("predefined_type") else "")
            node(iid, "ifc", iid[4:], iid[4:], {"bsdd_uri": ifc.get("bsdd_uri")})
            edges.add((aid, "maps_to_ifc", iid, 1.0, ev))
            edges.add((f"class:{cls}", "maps_to_ifc", iid, 1.0, ev))
        if lvl.get("name"):
            lid = f"level:{model}:{lvl['name']}"
            node(lid, "level", lvl["name"], lvl["name"], {"elevation_mm": lvl.get("elevation_mm")})
            edges.add((aid, "on_level", lid, 1.0 if lvl.get("matched") else 0.5, ev))
        for m in c.get("materials") or []:
            name = m.get("sketchup_material")
            if name:
                mid = f"material:{model}:{name}"
                node(mid, "material", name, name, m)
                edges.add((aid, "uses_material", mid, 1.0, ev))
        for t in (c.get("tag") or {}).get("current") or []:
            edges.add((aid, "tagged", node(f"tag:{model}:{t}", "tag", t, t), 1.0, ev))
        crec = rec.get("class_recipe")
        r = recipes.get(cls)
        if crec or r:
            rid = f"recipe:{cls}"
            node(rid, "recipe", cls, f"{cls} recipe", {"path": crec or (r and r["path"]),
                 "method": rec.get("method") or (r and r["data"].get("method")),
                 "method_ko": rec.get("method_ko") or (r and r["data"].get("method_ko"))})
            edges.add((aid, "made_by", rid, 1.0, ev))
            edges.add((f"class:{cls}", "made_by", rid, 1.0, ev))
        if c.get("definition_ref"):
            edges.add((aid, "instance_of", c["definition_ref"], 1.0, ev))
        if c.get("card_kind") == "instance" and src.get("parent_pid") is not None:
            parent = by_pid.get((model, src["parent_pid"]))
            if parent:
                edges.add((parent, "contains", aid, 1.0, ev))
        for child in rec.get("child_definitions") or []:
            cid = def_by_name.get((model, child))
            if cid:
                edges.add((aid, "contains", cid, 1.0, ev))

    for rcls, r in recipes.items():
        rid = f"recipe:{rcls}"
        node(rid, "recipe", rcls, f"{rcls} recipe", {"path": rel(r["path"]), "method": r["data"].get("method"),
             "method_ko": r["data"].get("method_ko")})

    con.executemany("INSERT INTO node VALUES (?,?,?,?,?)", nodes.values())
    con.executemany("INSERT INTO edge VALUES (?,?,?,?,?)", sorted(e for e in edges if e[2] in nodes or e[2].startswith("su-")))
    for aid, t in texts.items():
        con.execute("INSERT INTO search_fts VALUES (?,?)", (aid, t))
        con.execute("INSERT INTO search_tri VALUES (?,?)", (aid, t))

    model_name = "none"
    if embed:
        emb = embedder or make_embedder()
        ids = sorted(texts)
        vecs = emb.embed([texts[i] for i in ids])
        con.executemany("INSERT INTO node_vec VALUES (?,?)", [(i, _pack(v)) for i, v in zip(ids, vecs)])
        model_name = emb.model
    counts = {
        "cards": len(texts),
        "nodes": len(nodes),
        "edges": con.execute("SELECT count(*) FROM edge").fetchone()[0],
        "vectors": con.execute("SELECT count(*) FROM node_vec").fetchone()[0],
        "by_kind": dict(con.execute("SELECT kind, count(*) FROM node GROUP BY kind ORDER BY kind").fetchall()),
        "by_rel": dict(con.execute("SELECT rel, count(*) FROM edge GROUP BY rel ORDER BY rel").fetchall()),
        "models": sorted({r[0] for r in con.execute("SELECT model FROM asset")}),
    }
    meta = {"schema": SCHEMA, "card_schema": CARD_SCHEMA, "embedding_model": model_name,
            "cards_sha256": digest.hexdigest(), "counts": counts}
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
    con.commit()
    con.close()
    os.replace(tmp, out_path)
    return meta


# ---------------------------------------------------------------- query
def _dims_mm(query: str) -> list[float]:
    out = []
    for num, unit in _DIM_RE.findall(query):
        v = float(num) * {"mm": 1, "cm": 10, "m": 1000}[unit.lower()]
        out.append(v)
    return out


def _expand_terms(query: str) -> tuple[list[str], set[str]]:
    q = _DIM_RE.sub(" ", query.lower())
    terms = [t for t in _TOKEN_RE.findall(q) if t]
    classes = set()
    for cls, words in LEXICON.items():
        for w in words:
            if any(w == t or (len(w) >= 2 and w in t) for t in terms):
                classes.add(cls)
    return terms, classes


def _fts_quote(t: str) -> str:
    return '"' + t.replace('"', '""') + '"'


class AssetIndex:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.con = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.meta = {r["key"]: json.loads(r["value"]) for r in self.con.execute("SELECT * FROM meta")}
        self._vecs: dict[str, array] | None = None
        self._embedder = None

    def close(self) -> None:
        self.con.close()

    def _vectors(self) -> dict[str, array]:
        if self._vecs is None:
            self._vecs = {r["id"]: _unpack(r["vec"]) for r in self.con.execute("SELECT id, vec FROM node_vec")}
        return self._vecs

    def search(self, query: str, k: int = 10, *, expand: int = 2, model: str | None = None,
               cls: str | None = None, card_kind: str | None = None, include_inside_block: bool = False) -> dict[str, Any]:
        terms, classes = _expand_terms(query)
        dims = _dims_mm(query)
        channels: dict[str, list[str]] = {}
        if terms:
            match = " OR ".join(_fts_quote(t) for t in terms)
            channels["bm25"] = [r[0] for r in self.con.execute(
                "SELECT id FROM search_fts WHERE search_fts MATCH ? ORDER BY bm25(search_fts) LIMIT 200", (match,))]
            tri = [t for t in terms if len(t) >= 3]
            if tri:
                channels["trigram"] = [r[0] for r in self.con.execute(
                    "SELECT id FROM search_tri WHERE search_tri MATCH ? ORDER BY bm25(search_tri) LIMIT 200",
                    (" OR ".join(_fts_quote(t) for t in tri),))]
        if classes:
            channels["class"] = [r[0] for r in self.con.execute(
                f"SELECT id FROM asset WHERE class IN ({','.join('?' * len(classes))}) ORDER BY card_kind, confidence DESC",
                sorted(classes))]
        emb_model = self.meta.get("embedding_model")
        if emb_model and emb_model != "none":
            if self._embedder is None:
                self._embedder = make_embedder(emb_model)
            qv = self._embedder.embed([query], query=True)[0]
            scored = sorted(((sum(a * b for a, b in zip(qv, v)), i) for i, v in self._vectors().items()), reverse=True)
            channels["vector"] = [i for _, i in scored[:200]]
        if dims:
            rows = self.con.execute("SELECT id, height_mm, length_mm, width_mm, thickness_mm FROM asset").fetchall()
            def dist(r):
                vals = [r[c] for c in ("height_mm", "length_mm", "width_mm", "thickness_mm") if r[c]]
                return min((abs(v - d) / d for v in vals for d in dims), default=9.0)
            near = sorted((dist(r), r["id"]) for r in rows)
            channels["dims"] = [i for dd, i in near if dd <= 0.15][:200]

        weights = {"bm25": 1.0, "trigram": 0.7, "vector": 0.8, "class": 1.2, "dims": 0.6}
        fused: dict[str, float] = defaultdict(float)
        hits: dict[str, list[str]] = defaultdict(list)
        for ch, ids in channels.items():
            for rank, i in enumerate(ids):
                fused[i] += weights[ch] / (RRF_K + rank + 1)
                hits[i].append(ch)
        filt = ["1=1"]
        args: list[Any] = []
        if model:
            filt.append("model=?"); args.append(model)
        if cls:
            filt.append("class=?"); args.append(cls)
        if card_kind:
            filt.append("card_kind=?"); args.append(card_kind)
        if not include_inside_block:
            filt.append("inside_block=0")
        allowed = {r[0] for r in self.con.execute(f"SELECT id FROM asset WHERE {' AND '.join(filt)}", args)}
        ranked = sorted(((s * (1 + 0.15 * (len(hits[i]) - 1)), i) for i, s in fused.items() if i in allowed), reverse=True)[:k]
        results = []
        for score, i in ranked:
            a = dict(self.con.execute("SELECT * FROM asset WHERE id=?", (i,)).fetchone())
            a.pop("text", None)
            asset_file = None
            if a.get("skp_path"):
                asset_file = f"{a['asset_root']}/{a['skp_path']}" if a.get("asset_root") else a["skp_path"]
            results.append({"id": i, "score": round(score, 6), "channels": hits[i], **a, "asset_file": asset_file,
                            "context": self.neighbourhood(i, depth=expand) if expand else []})
        return {"query": query, "classes": sorted(classes), "dims_mm": dims, "embedding_model": emb_model,
                "results": results}

    def neighbourhood(self, nid: str, depth: int = 2, limit: int = 40) -> list[dict[str, Any]]:
        out, seen, frontier = [], {nid}, [nid]
        follow = {"instance_of", "in_class", "maps_to_ifc", "uses_material", "on_level", "made_by", "contains", "tagged"}
        for d in range(1, depth + 1):
            nxt = []
            for src in frontier:
                for r in self.con.execute(
                    "SELECT e.rel, e.dst, n.kind, n.label, n.props_json FROM edge e LEFT JOIN node n ON n.id=e.dst "
                    "WHERE e.src=? ORDER BY e.rel, e.dst", (src,)):
                    if r["rel"] not in follow or r["dst"] in seen:
                        continue
                    if d > 1 and r["rel"] in {"contains", "tagged"}:
                        continue
                    seen.add(r["dst"])
                    out.append({"from": src, "rel": r["rel"], "id": r["dst"], "kind": r["kind"], "label": r["label"],
                                "props": json.loads(r["props_json"] or "{}"), "hops": d, "weight": round(0.5 ** (d - 1), 3)})
                    if r["kind"] in {"asset", "class"}:
                        nxt.append(r["dst"])
                    if len(out) >= limit:
                        return out
            frontier = nxt
        return out


def default_index_path() -> Path:
    if os.getenv("SION_ASSET_INDEX"):
        return Path(os.environ["SION_ASSET_INDEX"])
    root = os.getenv("SION_STORAGE_ROOT")
    if root:
        return Path(root) / "SketchUp-Assets" / "_index" / DEFAULT_INDEX_NAME
    return Path("data/assets/sketchup/_index") / DEFAULT_INDEX_NAME


def write_manifest(meta: dict[str, Any], index_path: Path, out: Path) -> None:
    m = dict(meta)
    m["index_file"] = index_path.name
    m["index_bytes"] = index_path.stat().st_size
    m["index_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


BLOCK_CLASSES = {"tree", "person", "furniture"}


def library_index(card_roots: list[Path]) -> dict[str, dict[str, dict[str, Any]]]:
    """Per-model ``index.json`` for ``scripts/sketchup/generators/place_block.rb``.

    ``{asset_id: {path, class, ...}}`` where ``path`` is relative to the model's asset library
    (``asset_file.root``, e.g. ``SketchUp-Assets/ontology-objects/0914-meeting``). Keys are the card
    ``asset_id`` and the alias ``<model>:<class>:<name>``. Trees, people and furniture are one block =
    one asset: parts inside a block are never listed separately.
    """
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for _, c in iter_cards(card_roots):
        af = c.get("asset_file") or {}
        if not af.get("skp") or c.get("inside_block"):
            continue
        model, cls = c.get("model") or "", c.get("class") or "unclassified"
        entry = {"path": af["skp"], "class": cls, "asset_id": c["asset_id"], "card_kind": c.get("card_kind"),
                 "block": bool(c.get("block")) or cls in BLOCK_CLASSES, "sha256": af.get("sha256"),
                 "thumbnail": af.get("thumbnail"), "root": af.get("root"),
                 "ifc": (c.get("ifc") or {}).get("entity"), "review_state": c.get("review_state")}
        lib = out[model]
        lib.setdefault(c["asset_id"], entry)
        alias = f"{model}:{cls}:{_card_name(c)}"
        if c.get("card_kind") == "definition" or alias not in lib:
            lib[alias] = entry
    return {m: dict(sorted(v.items())) for m, v in sorted(out.items())}


def write_library_indexes(card_roots: list[Path], out_dir: Path) -> dict[str, int]:
    counts = {}
    for model, entries in library_index(card_roots).items():
        d = Path(out_dir) / model
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        counts[model] = len(entries)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SketchUp BIM asset index (FTS5 + trigram + vectors + graph)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--cards", nargs="+", default=["data/assets/sketchup"])
    b.add_argument("--recipes", default="data/assets/sketchup/recipes")
    b.add_argument("--out", default=None)
    b.add_argument("--manifest", default=None)
    b.add_argument("--no-embed", action="store_true")
    b.add_argument("--library-index-dir", default=None,
                   help="write <dir>/<model>/index.json for place_block.rb (e.g. G:/내 드라이브/SketchUp-Assets/ontology-objects)")
    q = sub.add_parser("query")
    q.add_argument("text")
    q.add_argument("--index", default=None)
    q.add_argument("-k", type=int, default=5)
    q.add_argument("--expand", type=int, default=2)
    q.add_argument("--class", dest="cls")
    q.add_argument("--model")
    q.add_argument("--include-inside-block", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = Path(a.out) if a.out else default_index_path()
        meta = build_index([Path(c) for c in a.cards], out, recipe_dir=Path(a.recipes), embed=not a.no_embed,
                           base=Path.cwd())
        if a.library_index_dir:
            meta = {**meta, "library_index": write_library_indexes([Path(c) for c in a.cards], Path(a.library_index_dir))}
        if a.manifest:
            write_manifest(meta, out, Path(a.manifest))
        print(json.dumps({"index": str(out), **meta}, ensure_ascii=False, indent=1))
        return 0
    idx = AssetIndex(Path(a.index) if a.index else default_index_path())
    res = idx.search(a.text, a.k, expand=a.expand, cls=a.cls, model=a.model, include_inside_block=a.include_inside_block)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
