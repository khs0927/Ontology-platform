"""Convert graph exports (Sites/HTML pages, D3, vis.js, Cytoscape, Mermaid, GraphML,
``ontology-map-export/v1``) into the canonical ``sion-map-export/v1`` contract.

Rules:

* Only edges that are written down in the source with explicit endpoints are
  emitted. Nothing is inferred from layout, order, proximity or label text.
* Every node and edge carries provenance: source file, its SHA-256, the detected
  format and a locator inside the file.
* Converted edges are ``unverified`` review candidates by default
  (``properties.candidate = True``); a reviewer promotes them through
  ``/api/v1/relations/candidates/{id}/approve``.
* Self-loops with a typed relation, duplicate (source, type, target) triples and
  edges whose endpoints are not declared nodes are reported in ``issues`` and
  dropped, never repaired.

Only the standard library is used.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from sion_ingestion.map_import import MapExport

KNOWN_RELATION_TYPES = frozenset(
    {
        "RELATED_TO",
        "PART_OF",
        "USES",
        "PRODUCES",
        "DERIVED_FROM",
        "REFERENCES",
        "IMPLEMENTS",
        "DEPENDS_ON",
        "CONNECTS_TO",
        "SUPPORTS",
        "EXTRACTED_FROM",
        "EVIDENCED_BY",
        "SUPERSEDES",
        "VERSION_OF",
        "VALIDATES",
    }
)
KNOWN_ENTITY_TYPES = frozenset(
    {
        "Entity",
        "Project",
        "Tool",
        "Concept",
        "Document",
        "Artifact",
        "Dataset",
        "SystemComponent",
        "Workflow",
        "Decision",
        "Deliverable",
    }
)
# Plain-language edge labels that unambiguously name one of the core relation types.
_RELATION_ALIASES = {
    "uses": "USES",
    "use": "USES",
    "part of": "PART_OF",
    "partof": "PART_OF",
    "belongs to": "PART_OF",
    "produces": "PRODUCES",
    "derived from": "DERIVED_FROM",
    "references": "REFERENCES",
    "refers to": "REFERENCES",
    "implements": "IMPLEMENTS",
    "depends on": "DEPENDS_ON",
    "requires": "DEPENDS_ON",
    "connects to": "CONNECTS_TO",
    "supports": "SUPPORTS",
    "extracted from": "EXTRACTED_FROM",
    "evidenced by": "EVIDENCED_BY",
    "supersedes": "SUPERSEDES",
    "version of": "VERSION_OF",
    "validates": "VALIDATES",
    "verifies": "VALIDATES",
    "related to": "RELATED_TO",
}
FORMATS = ("sion-map-export", "ontology-map-export", "d3", "vis", "cytoscape", "mermaid", "graphml")


class GraphExportError(ValueError):
    """The input holds no recognisable graph, or the graph fails validation."""


@dataclass
class RawNode:
    id: str
    label: str
    entity_type: str | None = None
    category: str | None = None
    description: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    locator: str = ""


@dataclass
class RawEdge:
    source: str
    target: str
    label: str | None = None
    id: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    locator: str = ""


@dataclass
class RawGraph:
    format: str
    nodes: list[RawNode]
    edges: list[RawEdge]
    locator: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversionReport:
    source_path: str | None
    sha256: str | None
    format: str
    node_count: int
    edge_count: int
    issues: list[str]
    relation_type_counts: dict[str, int]
    graphs_found: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


# --------------------------------------------------------------------------- helpers


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def _endpoint(value: Any) -> str | None:
    """D3 replaces link endpoints with node objects after layout; accept both."""
    if isinstance(value, dict):
        return _text(value.get("id") if value.get("id") is not None else value.get("name"))
    return _text(value)


def normalize_relation_type(label: str | None) -> tuple[str, str | None]:
    """Return (relation_type_id, original_label_if_not_exact)."""
    if not label:
        return "RELATED_TO", None
    stripped = label.strip()
    candidate = re.sub(r"[\s\-]+", "_", stripped).upper()
    if candidate in KNOWN_RELATION_TYPES:
        return candidate, None if candidate == stripped else stripped
    alias = _RELATION_ALIASES.get(re.sub(r"[_\-]+", " ", stripped).lower().strip())
    if alias:
        return alias, stripped
    return "RELATED_TO", stripped


def _slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", text.strip()).strip("-").lower()
    return slug[:120] or hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- parsers


def _from_sion(doc: dict, locator: str) -> RawGraph:
    nodes = [
        RawNode(
            id=str(n["stable_key"]),
            label=str(n.get("name") or n["stable_key"]),
            entity_type=n.get("entity_type_id"),
            category=n.get("category"),
            description=n.get("description"),
            properties=dict(n.get("properties") or {}),
            locator=f"{locator}nodes[{i}]",
        )
        for i, n in enumerate(doc.get("nodes") or [])
    ]
    edges = [
        RawEdge(
            source=str(e["source_stable_key"]),
            target=str(e["target_stable_key"]),
            label=e.get("relation_type_id"),
            id=e.get("stable_key"),
            properties=dict(e.get("properties") or {}),
            locator=f"{locator}edges[{i}]",
        )
        for i, e in enumerate(doc.get("edges") or [])
    ]
    meta = {k: doc.get(k) for k in ("source", "expected_node_count", "expected_edge_count") if k in doc}
    return RawGraph("sion-map-export", nodes, edges, locator, meta)


def _from_ontology_map(doc: dict, locator: str) -> RawGraph:
    nodes = []
    for i, n in enumerate(doc.get("nodes") or []):
        props = dict(n.get("properties") or {})
        description = props.pop("description", None) if isinstance(props.get("description"), str) else None
        nodes.append(
            RawNode(
                id=str(n["id"]),
                label=str(n.get("label") or n.get("name") or n["id"]),
                entity_type=n.get("entity_type_id"),
                category=n.get("category_id") or n.get("category"),
                description=description,
                properties=props,
                locator=f"{locator}nodes[{i}]",
            )
        )
    edges = [
        RawEdge(
            source=str(r["source_id"]),
            target=str(r["target_id"]),
            label=r.get("relation_type_id") or r.get("type"),
            id=_text(r.get("id")),
            properties=dict(r.get("properties") or {}),
            locator=f"{locator}relations[{i}]",
        )
        for i, r in enumerate(doc.get("relations") or doc.get("edges") or [])
    ]
    meta = {
        "source": doc.get("source"),
        "source_uri": doc.get("source_uri"),
        "namespace": doc.get("namespace"),
        "expected_node_count": doc.get("expected_node_count"),
        "expected_edge_count": doc.get("expected_relation_count", doc.get("expected_edge_count")),
    }
    return RawGraph("ontology-map-export", nodes, edges, locator, {k: v for k, v in meta.items() if v is not None})


def _node_from_plain(item: Any, index: int, locator: str) -> RawNode | None:
    if isinstance(item, (str, int)):
        return RawNode(id=str(item), label=str(item), locator=f"{locator}[{index}]")
    if not isinstance(item, dict):
        return None
    data = item.get("data") if isinstance(item.get("data"), dict) else item
    node_id = _text(data.get("id"))
    if node_id is None:
        node_id = _text(data.get("key")) or _text(data.get("name"))
    if node_id is None:
        return None
    label = _text(data.get("label")) or _text(data.get("name")) or _text(data.get("title")) or node_id
    props = {
        k: v
        for k, v in data.items()
        if k not in {"id", "key", "label", "name", "title", "x", "y", "vx", "vy", "fx", "fy", "index"}
        and isinstance(v, (str, int, float, bool))
    }
    return RawNode(
        id=node_id,
        label=label,
        entity_type=_text(data.get("entity_type_id")) or _text(data.get("type")),
        category=_text(data.get("category")) or _text(data.get("group")),
        description=_text(data.get("description")),
        properties=props,
        locator=f"{locator}[{index}]",
    )


def _edge_from_plain(item: Any, index: int, locator: str) -> RawEdge | None:
    if not isinstance(item, dict):
        return None
    data = item.get("data") if isinstance(item.get("data"), dict) else item
    source = _endpoint(data.get("source", data.get("from")))
    target = _endpoint(data.get("target", data.get("to")))
    if source is None or target is None:
        return None
    label = (
        _text(data.get("relation_type_id"))
        or _text(data.get("type"))
        or _text(data.get("label"))
        or _text(data.get("relation"))
        or _text(data.get("name"))
    )
    props = {
        k: v
        for k, v in data.items()
        if k not in {"source", "target", "from", "to", "id", "index"} and isinstance(v, (str, int, float, bool))
    }
    return RawEdge(source=source, target=target, label=label, id=_text(data.get("id")), properties=props, locator=f"{locator}[{index}]")


def _plain_graph(fmt: str, raw_nodes: list, raw_edges: list, locator: str, node_key: str, edge_key: str) -> RawGraph:
    nodes = [n for i, item in enumerate(raw_nodes) if (n := _node_from_plain(item, i, f"{locator}{node_key}")) is not None]
    edges = [e for i, item in enumerate(raw_edges) if (e := _edge_from_plain(item, i, f"{locator}{edge_key}")) is not None]
    return RawGraph(fmt, nodes, edges, locator)


def graphs_from_json(doc: Any, locator: str = "$.") -> list[RawGraph]:
    """Detect graph structures in a decoded JSON value (searches nested objects)."""
    found: list[RawGraph] = []

    def visit(value: Any, path: str, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(value, dict):
            schema = str(value.get("schema") or value.get("schema_version") or "")
            if schema.startswith("sion-map-export/") and isinstance(value.get("edges"), list):
                found.append(_from_sion(value, path))
                return
            if schema.startswith("ontology-map-export/") or (
                isinstance(value.get("relations"), list)
                and isinstance(value.get("nodes"), list)
                and any(isinstance(r, dict) and "source_id" in r for r in value["relations"])
            ):
                found.append(_from_ontology_map(value, path))
                return
            elements = value.get("elements")
            if isinstance(elements, dict) and isinstance(elements.get("edges"), list):
                found.append(_plain_graph("cytoscape", elements.get("nodes") or [], elements["edges"], f"{path}elements.", "nodes", "edges"))
                return
            if isinstance(elements, list) and any(isinstance(e, dict) and isinstance(e.get("data"), dict) for e in elements):
                cy_nodes = [e for e in elements if isinstance(e, dict) and isinstance(e.get("data"), dict) and "source" not in e["data"]]
                cy_edges = [e for e in elements if isinstance(e, dict) and isinstance(e.get("data"), dict) and "source" in e["data"]]
                found.append(_plain_graph("cytoscape", cy_nodes, cy_edges, f"{path}elements", "", ""))
                return
            if isinstance(value.get("nodes"), list) and isinstance(value.get("links"), list):
                found.append(_plain_graph("d3", value["nodes"], value["links"], path, "nodes", "links"))
                return
            if isinstance(value.get("nodes"), list) and isinstance(value.get("edges"), list):
                edges = value["edges"]
                fmt = "vis" if any(isinstance(e, dict) and "from" in e for e in edges) else "d3"
                found.append(_plain_graph(fmt, value["nodes"], edges, path, "nodes", "edges"))
                return
            for key, child in value.items():
                visit(child, f"{path}{key}.", depth + 1)
        elif isinstance(value, list):
            for i, child in enumerate(value[:200]):
                visit(child, f"{path}[{i}].", depth + 1)

    visit(doc, locator, 0)
    return found


_MERMAID_HEADER = re.compile(r"^\s*(?:flowchart|graph)\b[^\n]*$", re.IGNORECASE | re.MULTILINE)
_MERMAID_NODE = r"([A-Za-z0-9_\-가-힣]+)\s*(?:\[\[?\(?\"?([^\]\)\"]*)\"?\)?\]?\]|\(\(?\"?([^\)\"]*)\"?\)?\)|\{\"?([^}\"]*)\"?\})?"
_MERMAID_EDGE = re.compile(
    _MERMAID_NODE
    + r"\s*(?:--\s*([^->|]+?)\s*-->|-->\|([^|]*)\||-\.->\|([^|]*)\||==>\|([^|]*)\||-->|-\.->|==>|---)\s*"
    + _MERMAID_NODE
)
_MERMAID_LONE_NODE = re.compile(r"^\s*" + _MERMAID_NODE + r"\s*$")


def graphs_from_mermaid(text: str, locator: str = "mermaid") -> list[RawGraph]:
    graphs: list[RawGraph] = []
    for block_index, header in enumerate(_MERMAID_HEADER.finditer(text)):
        start = header.end()
        next_header = _MERMAID_HEADER.search(text, start)
        end_fence = text.find("```", start)
        end = min(x for x in (next_header.start() if next_header else len(text), end_fence if end_fence >= 0 else len(text), len(text)))
        body = text[start:end]
        labels: dict[str, str] = {}
        order: list[str] = []
        edges: list[RawEdge] = []

        def remember(node_id: str, *candidates: str | None) -> None:
            label = next((c.strip() for c in candidates if c and c.strip()), None)
            if node_id not in labels:
                order.append(node_id)
                labels[node_id] = html.unescape(label) if label else node_id
            elif label and labels[node_id] == node_id:
                labels[node_id] = html.unescape(label)

        for line_no, line in enumerate(body.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("%%", "classDef", "class ", "style ", "linkStyle", "subgraph", "end", "click ", "direction")):
                continue
            # chained edges (A --> B --> C) are matched pairwise
            position = 0
            matched = False
            while True:
                match = _MERMAID_EDGE.search(stripped, position)
                if not match:
                    break
                matched = True
                g = match.groups()
                src, tgt = g[0], g[8]
                remember(src, g[1], g[2], g[3])
                remember(tgt, g[9], g[10], g[11])
                label = next((x.strip() for x in g[4:8] if x and x.strip()), None)
                edges.append(RawEdge(source=src, target=tgt, label=label, locator=f"{locator}[{block_index}]:line:{line_no}"))
                position = match.start(9) if match.start(9) > match.start() else match.end()
            if not matched:
                lone = _MERMAID_LONE_NODE.match(stripped)
                if lone and any(lone.groups()[1:4]):
                    remember(lone.group(1), *lone.groups()[1:4])
        nodes = [RawNode(id=node_id, label=labels[node_id], locator=f"{locator}[{block_index}]") for node_id in order]
        if edges:
            graphs.append(RawGraph("mermaid", nodes, edges, f"{locator}[{block_index}]"))
    return graphs


def graphs_from_graphml(text: str, locator: str = "graphml") -> list[RawGraph]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise GraphExportError(f"GraphML could not be parsed: {exc}") from exc
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    keys = {k.get("id"): (k.get("attr.name") or k.get("id")) for k in root.iter(f"{ns}key")}
    graphs: list[RawGraph] = []
    for gi, graph in enumerate(root.iter(f"{ns}graph")):
        nodes: list[RawNode] = []
        edges: list[RawEdge] = []
        for ni, node in enumerate(graph.findall(f"{ns}node")):
            data = {keys.get(d.get("key"), d.get("key")): (d.text or "").strip() for d in node.findall(f"{ns}data")}
            label = data.pop("label", None) or data.pop("name", None) or node.get("id")
            nodes.append(RawNode(id=node.get("id"), label=label, category=data.pop("category", None), properties=data, locator=f"{locator}[{gi}].node[{ni}]"))
        for ei, edge in enumerate(graph.findall(f"{ns}edge")):
            data = {keys.get(d.get("key"), d.get("key")): (d.text or "").strip() for d in edge.findall(f"{ns}data")}
            label = data.pop("relation_type_id", None) or data.pop("type", None) or data.pop("label", None)
            edges.append(RawEdge(source=edge.get("source"), target=edge.get("target"), label=label, id=edge.get("id"), properties=data, locator=f"{locator}[{gi}].edge[{ei}]"))
        if edges:
            graphs.append(RawGraph("graphml", nodes, edges, f"{locator}[{gi}]"))
    return graphs


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, str]] = []  # (kind, attrs, text)
        self._stack: list[tuple[str, str]] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "script":
            self._stack.append(("script", attr.get("type") or ""))
            self._buffer = []
        elif tag in {"pre", "div", "code"} and "mermaid" in (attr.get("class") or ""):
            self._stack.append(("mermaid", tag))
            self._buffer = []

    def handle_endtag(self, tag):
        if self._stack and ((tag == "script" and self._stack[-1][0] == "script") or (self._stack[-1][0] == "mermaid" and tag == self._stack[-1][1])):
            kind, attr = self._stack.pop()
            self.blocks.append((kind, attr, "".join(self._buffer)))
            self._buffer = []

    def handle_data(self, data):
        if self._stack:
            self._buffer.append(data)


_JS_ASSIGN = re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*", re.MULTILINE)
_VIS_DATASET = re.compile(r"new\s+vis\.DataSet\(\s*", re.MULTILINE)


def _balanced_literal(text: str, start: int) -> str | None:
    """Return the JSON-ish object/array literal starting at ``text[start]``."""
    if start >= len(text) or text[start] not in "[{":
        return None
    opening = text[start]
    closing = "]" if opening == "[" else "}"
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, min(len(text), start + 5_000_000)):
        ch = text[index]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1] if ch == closing else None
    return None


def _loads_jsish(literal: str) -> Any:
    try:
        return json.loads(literal)
    except json.JSONDecodeError:
        pass
    # Tolerate the common JS object-literal forms: unquoted keys, single quotes, trailing commas.
    converted = re.sub(r"(?<=[{,\s])([A-Za-z_$][\w$]*)\s*:", r'"\1":', literal)
    converted = re.sub(r"'((?:[^'\\]|\\.)*)'", lambda m: json.dumps(m.group(1).replace("\\'", "'")), converted)
    converted = re.sub(r",\s*([}\]])", r"\1", converted)
    return json.loads(converted)


def graphs_from_script(script: str, locator: str) -> list[RawGraph]:
    graphs: list[RawGraph] = []
    variables: dict[str, Any] = {}
    for match in _JS_ASSIGN.finditer(script):
        literal = _balanced_literal(script, match.end())
        if literal is None:
            continue
        try:
            variables[match.group(1)] = _loads_jsish(literal)
        except (json.JSONDecodeError, ValueError):
            continue
    datasets: list[Any] = []
    for match in _VIS_DATASET.finditer(script):
        literal = _balanced_literal(script, match.end())
        if literal is None:
            continue
        try:
            datasets.append(_loads_jsish(literal))
        except (json.JSONDecodeError, ValueError):
            continue
    for name, value in variables.items():
        graphs.extend(graphs_from_json(value, f"{locator}:{name}."))
    if not graphs:
        # separate `const nodes = [...]; const edges|links = [...]` declarations
        node_list = next((variables[k] for k in ("nodes", "graphNodes", "NODES") if isinstance(variables.get(k), list)), None)
        edge_name = next((k for k in ("edges", "links", "graphEdges", "graphLinks", "EDGES", "LINKS", "relations") if isinstance(variables.get(k), list)), None)
        if node_list is not None and edge_name is not None:
            graphs.extend(graphs_from_json({"nodes": node_list, edge_name if edge_name in {"links", "edges", "relations"} else "edges": variables[edge_name]}, f"{locator}:"))
        elif len(datasets) >= 2:
            graphs.extend(graphs_from_json({"nodes": datasets[0], "edges": datasets[1]}, f"{locator}:vis.DataSet."))
    return graphs


def graphs_from_html(text: str, locator: str = "html") -> list[RawGraph]:
    collector = _ScriptCollector()
    collector.feed(text)
    graphs: list[RawGraph] = []
    for index, (kind, attr, body) in enumerate(collector.blocks):
        block_locator = f"{locator}:{kind}[{index}]"
        if kind == "mermaid":
            graphs.extend(graphs_from_mermaid(body, block_locator))
            continue
        if "json" in attr.lower():
            try:
                graphs.extend(graphs_from_json(json.loads(body), f"{block_locator}:$."))
            except json.JSONDecodeError:
                pass
            continue
        graphs.extend(graphs_from_script(body, block_locator))
    return graphs


def detect_graphs(text: str, *, suffix: str = "") -> list[RawGraph]:
    suffix = suffix.lower()
    stripped = text.lstrip("\ufeff").lstrip()
    if suffix in {".graphml", ".xml"} or stripped.startswith("<?xml") and "<graphml" in stripped[:2000]:
        return graphs_from_graphml(stripped)
    if suffix in {".json", ".geojson"} or stripped[:1] in "[{":
        try:
            return graphs_from_json(json.loads(stripped))
        except json.JSONDecodeError:
            if suffix == ".json":
                raise GraphExportError("JSON could not be decoded")
    if suffix in {".mmd", ".mermaid"}:
        return graphs_from_mermaid(stripped)
    if suffix in {".html", ".htm"} or "<html" in stripped[:4000].lower() or "<script" in stripped.lower():
        return graphs_from_html(stripped)
    if suffix in {".js", ".mjs", ".ts"}:
        return graphs_from_script(stripped, "script")
    return graphs_from_mermaid(stripped)  # markdown with ```mermaid blocks, or plain mermaid text


# --------------------------------------------------------------------------- conversion


def _resolve_nodes(graph: RawGraph) -> tuple[dict[str, RawNode], list[str]]:
    issues: list[str] = []
    by_id: dict[str, RawNode] = {}
    for node in graph.nodes:
        if node.id in by_id:
            issues.append(f"duplicate node id {node.id!r} at {node.locator}; first occurrence kept")
            continue
        by_id[node.id] = node
    return by_id, issues


def convert_graph(
    graph: RawGraph,
    *,
    namespace: str,
    source: str,
    provenance: dict[str, Any],
    default_entity_type: str = "Concept",
    as_candidates: bool = True,
    confidence: float | None = None,
    allow_implicit_nodes: bool = False,
) -> tuple[MapExport, list[str]]:
    by_id, issues = _resolve_nodes(graph)
    if allow_implicit_nodes:
        for edge in graph.edges:
            for endpoint in (edge.source, edge.target):
                if endpoint not in by_id:
                    by_id[endpoint] = RawNode(id=endpoint, label=endpoint, locator=edge.locator)
                    issues.append(f"node {endpoint!r} declared only by an edge at {edge.locator}")

    def key_for(node_id: str) -> str:
        return node_id if graph.format == "sion-map-export" else f"map:{namespace}:{_slug(node_id)}"

    nodes_out: list[dict[str, Any]] = []
    for node in by_id.values():
        entity_type = node.entity_type if node.entity_type in KNOWN_ENTITY_TYPES else default_entity_type
        properties = dict(node.properties)
        if node.entity_type and node.entity_type not in KNOWN_ENTITY_TYPES:
            properties["source_type"] = node.entity_type
        properties["provenance"] = {**provenance, "format": graph.format, "locator": node.locator, "source_node_id": node.id}
        nodes_out.append(
            {
                "stable_key": key_for(node.id),
                "entity_type_id": entity_type,
                "name": node.label[:500],
                "category": node.category,
                "description": node.description,
                "properties": properties,
            }
        )

    edges_out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in graph.edges:
        if edge.source not in by_id or edge.target not in by_id:
            issues.append(f"edge {edge.id or edge.locator} references an undeclared node; dropped")
            continue
        relation_type, original = normalize_relation_type(edge.label)
        if edge.source == edge.target and relation_type != "RELATED_TO":
            issues.append(f"typed self-loop {edge.id or edge.locator} ({relation_type}); dropped")
            continue
        triple = (edge.source, relation_type, edge.target)
        if triple in seen:
            issues.append(f"duplicate edge {edge.source} -{relation_type}-> {edge.target} at {edge.locator}; dropped")
            continue
        seen.add(triple)
        properties = dict(edge.properties)
        if original:
            properties["source_label"] = original
        properties["provenance"] = {**provenance, "format": graph.format, "locator": edge.locator, **({"source_edge_id": edge.id} if edge.id else {})}
        if as_candidates:
            properties["candidate"] = True
            properties["extractor"] = "sion-graph-export/v1"
        stable_key = (
            edge.id
            if graph.format == "sion-map-export" and edge.id
            else f"{key_for(edge.source)}:{relation_type}:{key_for(edge.target)}"
        )
        edges_out.append(
            {
                "stable_key": stable_key,
                "source_stable_key": key_for(edge.source),
                "target_stable_key": key_for(edge.target),
                "relation_type_id": relation_type,
                "confidence": confidence,
                "verification_state": "unverified" if as_candidates else "human_verified",
                "source_kind": "imported",
                "properties": properties,
            }
        )

    export = MapExport.model_validate(
        {
            "schema": "sion-map-export/v1",
            "source": source,
            "expected_node_count": len(nodes_out),
            "expected_edge_count": len(edges_out),
            "nodes": nodes_out,
            "edges": edges_out,
        }
    )
    return export, issues


def convert_file(
    path: str | Path,
    *,
    namespace: str | None = None,
    expected_nodes: int | None = None,
    expected_edges: int | None = None,
    as_candidates: bool = True,
    graph_index: int | None = None,
    source_uri: str | None = None,
    allow_implicit_nodes: bool = False,
) -> tuple[MapExport, ConversionReport]:
    """Convert one graph export file. Raises :class:`GraphExportError` on count mismatch or no graph."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig", errors="replace")
    graphs = detect_graphs(text, suffix=path.suffix)
    if not graphs:
        raise GraphExportError(f"no graph with explicit edges found in {path.name}")
    if graph_index is None:
        graph = max(graphs, key=lambda g: (len(g.edges), len(g.nodes)))
    else:
        if not 0 <= graph_index < len(graphs):
            raise GraphExportError(f"graph_index {graph_index} out of range (found {len(graphs)})")
        graph = graphs[graph_index]

    namespace = namespace or str(graph.meta.get("namespace") or _slug(path.stem))
    provenance = {
        "source_file": path.name,
        "source_sha256": digest,
        **({"source_uri": source_uri} if source_uri else {}),
        **({"declared_source_uri": graph.meta["source_uri"]} if graph.meta.get("source_uri") else {}),
    }
    source = f"graph-export:{graph.format}:{path.name}#sha256={digest[:16]}"
    export, issues = convert_graph(
        graph,
        namespace=namespace,
        source=source,
        provenance=provenance,
        as_candidates=as_candidates,
        allow_implicit_nodes=allow_implicit_nodes,
    )
    declared_nodes = graph.meta.get("expected_node_count")
    declared_edges = graph.meta.get("expected_edge_count")
    for label, want, got in (
        ("declared node count", declared_nodes, len(export.nodes)),
        ("declared edge count", declared_edges, len(export.edges)),
        ("expected node count", expected_nodes, len(export.nodes)),
        ("expected edge count", expected_edges, len(export.edges)),
    ):
        if want is not None and int(want) != got:
            raise GraphExportError(f"{label} mismatch: expected {want}, got {got}; issues: {issues[:5]}")

    counts: dict[str, int] = {}
    for edge in export.edges:
        counts[edge.relation_type_id] = counts.get(edge.relation_type_id, 0) + 1
    report = ConversionReport(
        source_path=str(path),
        sha256=digest,
        format=graph.format,
        node_count=len(export.nodes),
        edge_count=len(export.edges),
        issues=issues,
        relation_type_counts=dict(sorted(counts.items())),
        graphs_found=len(graphs),
    )
    return export, report


def compare_with_inventory(export: MapExport, inventory: dict[str, Any]) -> dict[str, Any]:
    """Compare node labels/counts with a ``sion-map-inventory/v1`` document."""
    labels = [node.name for node in export.nodes]
    visible = list(inventory.get("visible_labels") or [])
    categories: dict[str, int] = {}
    for node in export.nodes:
        if node.category:
            categories[node.category] = categories.get(node.category, 0) + 1
    expected_categories = {c["id"]: c.get("observed_count") for c in inventory.get("categories") or [] if "id" in c}
    return {
        "node_count": len(export.nodes),
        "edge_count": len(export.edges),
        "expected_node_count": inventory.get("observed_node_count"),
        "expected_edge_count": inventory.get("observed_relation_count"),
        "missing_labels": sorted(set(visible) - set(labels)),
        "extra_labels": sorted(set(labels) - set(visible)),
        "category_counts": dict(sorted(categories.items())),
        "category_mismatches": {
            cid: {"expected": want, "got": categories.get(cid, 0)}
            for cid, want in expected_categories.items()
            if want is not None and categories.get(cid, 0) != want
        },
        "matches": (
            len(export.nodes) == inventory.get("observed_node_count")
            and len(export.edges) == inventory.get("observed_relation_count")
            and set(visible) == set(labels)
        ),
    }


def attach_export_evidence(session, export: MapExport, *, source_uri: str) -> int:
    """One evidence row per imported edge, pointing at the edge's locator in the source file.

    Idempotent: an edge that already has evidence with the same locator is skipped.
    """
    from sion_api import models
    from sqlalchemy import select

    created = 0
    for edge in export.edges:
        relation = session.scalar(select(models.Relation).where(models.Relation.stable_key == edge.stable_key))
        if relation is None:
            continue
        provenance = edge.properties.get("provenance") or {}
        locator = str(provenance.get("locator") or "")
        exists = session.scalar(
            select(models.Evidence).where(
                models.Evidence.relation_id == relation.id,
                models.Evidence.source_locator == locator,
            )
        )
        if exists is not None:
            continue
        excerpt = json.dumps(
            {
                "source": provenance.get("source_node_id") or edge.source_stable_key,
                "target": edge.target_stable_key,
                "type": edge.relation_type_id,
                "source_edge_id": provenance.get("source_edge_id"),
                "source_label": edge.properties.get("source_label"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        session.add(
            models.Evidence(
                relation_id=relation.id,
                source_uri=source_uri,
                source_locator=locator,
                excerpt_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                confidence=edge.confidence,
                verification_state=edge.verification_state,
                extractor="sion-graph-export/v1",
                properties={"excerpt": excerpt, "provenance": provenance, "kind": "graph-export"},
            )
        )
        created += 1
    session.commit()
    return created
