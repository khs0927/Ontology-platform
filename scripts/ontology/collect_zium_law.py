"""Collect 2026-10-24 artifacts into a sion-map-export/v1 graph (+ JSON-LD).

Sources (read-only):
  * standards/zium/manifest.json            -> 지음 기준 항목 (Document / Concept gap)
  * <site-calls dir>/*.out.json              -> 법규·대지 MCP 호출 결과 (Dataset)
  * <templates dir> (dwt/skp/rte/rfa/smoke)  -> 템플릿·스모크 산출물 (Deliverable, sha256)

No values are invented: properties are copied from the source files.
Secrets: keys whose name looks like a credential are dropped.

Usage:
  python scripts/ontology/collect_zium_law.py --site-calls C:/CODE/grokbot-handoff/site-calls-20261024 \
      --templates C:/CODE/zium-templates --out runtime/ontology/zium_law_20261024
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SECRET_KEY = re.compile(r"(key|token|secret|password|serviceKey|apikey|LAW_OC)", re.I)
PROJECT = "project:goyeon-1525"
ZIUM = "standard:zium"
VERSION = "2026-10-24"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def scrub(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items() if not SECRET_KEY.search(str(k))}
    if isinstance(v, list):
        return [scrub(x) for x in v[:50]]
    if isinstance(v, str):
        return re.sub(r"(?i)(serviceKey|apikey|key|OC)=[^&\s\"]+", r"\1=***", v)[:2000]
    return v


class G:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}

    def node(self, key: str, typ: str, name: str, **props: Any) -> str:
        desc = props.pop("description", None)
        self.nodes.setdefault(key, {"stable_key": key, "entity_type_id": typ, "name": name[:500],
                                    "description": desc, "properties": scrub(props), "ontology_version": VERSION})
        return key

    def edge(self, s: str, rel: str, t: str, src: str = "file", **props: Any) -> None:
        k = f"{s}|{rel}|{t}"
        self.edges.setdefault(k, {"stable_key": k[:700], "source_stable_key": s, "target_stable_key": t,
                                  "relation_type_id": rel, "verification_state": "machine_verified",
                                  "source_kind": src, "confidence": 1.0, "properties": props})


def zium(g: G, manifest: Path) -> None:
    m = json.loads(manifest.read_text(encoding="utf-8"))
    g.node(ZIUM, "Concept", "지음(ZIUM) 설계 기준", description="지음 CAD/Revit/SketchUp 기준 묶음",
           manifest="standards/zium/manifest.json", manifest_version=m.get("version"))
    for stage, items in m.get("stages", {}).items():
        sk = g.node(f"{ZIUM}:{stage}", "Concept", f"지음 기준 - {stage}", stage=stage)
        g.edge(sk, "PART_OF", ZIUM)
        for it in items:
            typ = "Document" if it.get("status") == "found" else "Concept"
            k = g.node(f"{ZIUM}:{stage}:{it['id']}", typ, f"{it['id']} ({it.get('kind')})", **it)
            g.edge(k, "PART_OF", sk)
    doc = ROOT / "docs/standards/ZIUM_revit_v2_mapping.ko.md"
    if doc.exists():
        k = g.node("doc:zium-revit-v2-mapping", "Document", "ZIUM → Revit 템플릿 v2 매핑",
                   path="docs/standards/ZIUM_revit_v2_mapping.ko.md", sha256=sha256(doc))
        g.edge(k, "REFERENCES", ZIUM)


TEMPLATE_KIND = {".dwt": "AutoCAD 템플릿", ".dxf": "DXF", ".skp": "SketchUp", ".rte": "Revit 템플릿",
                 ".rfa": "Revit 패밀리", ".ifc": "IFC4", ".rvt": "Revit 모델", ".dwg": "DWG 시트"}


def templates(g: G, root: Path) -> None:
    if not root.exists():
        return
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in TEMPLATE_KIND or "_backup" in p.parts or re.search(r"\.\d{4}\.(rte|rfa)$", p.name):
            continue  # skip backups and Revit auto-versions (.0001.rte)
        rel = p.relative_to(root).as_posix()
        k = g.node(f"file:zium-templates/{rel}", "Deliverable", p.name, path=str(p), relpath=rel,
                   kind=TEMPLATE_KIND[p.suffix.lower()], size=p.stat().st_size, sha256=sha256(p))
        if rel.startswith("smoke/"):
            g.edge(k, "PART_OF", PROJECT)
        else:
            g.edge(k, "IMPLEMENTS", ZIUM)
    chain = ["smoke/GOYEON1525_mass.skp", "smoke/GOYEON1525_mass.ifc", "smoke/GOYEON1525_mass_ifc.rvt"]
    for a, b in zip(chain, chain[1:]):
        ka, kb = f"file:zium-templates/{a}", f"file:zium-templates/{b}"
        if ka in g.nodes and kb in g.nodes:
            g.edge(kb, "DERIVED_FROM", ka)
    dwg, dwt = "file:zium-templates/smoke/GOYEON1525_sheet.dwg", "file:zium-templates/autocad/ZIUM_template.dwt"
    if dwg in g.nodes and dwt in g.nodes:
        g.edge(dwg, "USES", dwt)


FINDINGS = [  # (key, label, (file, json path)) — values read from the call outputs, not typed in
    ("zone", "용도지역", ("sp_land_characteristics.out.json", "zone")),
    ("road_side", "접도(도로접면)", ("sp_land_characteristics.out.json", "road_side")),
    ("ledger_area", "대장면적 m2", ("sp_land_characteristics.out.json", "land_ledger_area_m2")),
    ("gis_area", "도형면적 m2", ("sp_parcel_geometry.out.json", "area_m2")),
    ("zones_split", "용도지역(걸침)", ("sp_land_use_plan.out.json", "zones")),
    ("areas", "지역·구역", ("sp_land_use_plan.out.json", "areas")),
    ("bcr", "건폐율 상한 %", ("sp_site_compliance.out.json", "bcr_pct")),
    ("far", "용적률 상한 %", ("sp_site_compliance.out.json", "far_pct")),
    ("bcr_source", "건폐율 근거", ("sp_site_compliance.out.json", "bcr_source")),
    ("buildings", "기존 건축물 수", ("sp_building_register.out.json", "building_count")),
]


def load(p: Path) -> Any:
    t = p.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return {"text": t}


def unwrap(v: Any) -> Any:
    """MCP outputs may be {content:[{text:'<json>'}]} or a JSON string."""
    if isinstance(v, dict) and isinstance(v.get("content"), list) and v["content"]:
        v = v["content"][0].get("text", v)
    if isinstance(v, dict) and set(v) == {"text"}:
        v = v["text"]
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return {"text": v}
    return v


def site(g: G, d: Path) -> None:
    g.node(PROJECT, "Project", "울산 울주군 웅촌면 고연리 1525", pnu="3171034026115250000", crs="EPSG:5186")
    if not d.exists():
        return
    outs: dict[str, Any] = {}
    for p in sorted(d.glob("*.out.json")):
        tool = p.name[: -len(".out.json")]
        server = {"kl": "korean-land", "sp": "site-pipeline"}.get(tool.split("_", 1)[0], "mcp")
        name = tool.split("_", 1)[1] if "_" in tool else tool
        tk = g.node(f"tool:mcp:{server}", "Tool", f"MCP {server}", server=server)
        data = unwrap(load(p))
        outs[p.name] = data
        args = d / f"{tool}.args.json"
        k = g.node(f"mcp-result:goyeon-1525:{server}:{name}", "Dataset", f"{server}.{name} 결과 (고연리 1525)",
                   tool=name, server=server, path=str(p), sha256=sha256(p),
                   args=unwrap(load(args)) if args.exists() else None,
                   top_keys=sorted(data)[:40] if isinstance(data, dict) else None)
        g.edge(tk, "PRODUCES", k, src="mcp")
        g.edge(k, "REFERENCES", PROJECT, src="mcp")
    for key, label, (fname, path) in FINDINGS:
        data = outs.get(fname)
        if not isinstance(data, dict) or path not in data:
            continue
        k = g.node(f"finding:goyeon-1525:{key}", "Concept", f"{label}: {data[path]}", value=data[path], label=label)
        g.edge(k, "PART_OF", PROJECT, src="mcp")
        server = "site-pipeline" if fname.startswith("sp_") else "korean-land"
        g.edge(k, "EXTRACTED_FROM", f"mcp-result:goyeon-1525:{server}:{fname[3:-len('.out.json')]}", src="mcp")


def jsonld(export: dict) -> dict:
    ctx = {"@vocab": "https://sion.local/ontology#", "name": "http://schema.org/name"}
    by = {}
    for n in export["nodes"]:
        by[n["stable_key"]] = {"@id": n["stable_key"], "@type": n["entity_type_id"], "name": n["name"],
                               **{k: v for k, v in n["properties"].items() if isinstance(v, (str, int, float, bool))}}
    for e in export["edges"]:
        by[e["source_stable_key"]].setdefault(e["relation_type_id"], []).append({"@id": e["target_stable_key"]})
    return {"@context": ctx, "@graph": list(by.values())}


def build(site_calls: Path, tpl: Path, manifest: Path) -> dict:
    g = G()
    zium(g, manifest)
    site(g, site_calls)
    templates(g, tpl)
    return {"schema": "sion-map-export/v1", "source": f"zium-law-collector/{VERSION}",
            "expected_node_count": len(g.nodes), "expected_edge_count": len(g.edges),
            "nodes": list(g.nodes.values()), "edges": list(g.edges.values())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-calls", type=Path, default=Path("C:/CODE/grokbot-handoff/site-calls-20261024"))
    ap.add_argument("--templates", type=Path, default=Path("C:/CODE/zium-templates"))
    ap.add_argument("--manifest", type=Path, default=ROOT / "standards/zium/manifest.json")
    ap.add_argument("--out", type=Path, default=ROOT / "runtime/ontology/zium_law_20261024")
    a = ap.parse_args(argv)
    exp = build(a.site_calls, a.templates, a.manifest)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".map.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    a.out.with_suffix(".jsonld").write_text(json.dumps(jsonld(exp), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"nodes": len(exp["nodes"]), "edges": len(exp["edges"]), "out": str(a.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
