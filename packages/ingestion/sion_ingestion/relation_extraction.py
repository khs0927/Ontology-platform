"""Evidence-backed relation *candidates* from documents, DXF drawings, IFC models
and (optionally) a LightRAG knowledge graph.

Nothing here asserts a fact. Every proposal is stored as a ``relations`` row with
``verification_state = 'unverified'``, ``source_kind = 'inferred'`` and
``properties.candidate = True``, plus one ``evidence`` row per supporting span
(source URI, locator, excerpt and its SHA-256). A reviewer approves or rejects it
through ``/api/v1/relations/candidates`` (see ``sion_api.review``).

Extractors
----------
* **rule**: two known entities in one sentence joined by an explicit verb phrase
  ("A uses B", "A depends on B", "A는 B를 사용", "A는 B를 검증", ...). Directional.
* **co-occurrence**: two known entities in the same sentence with no rule match,
  in at least ``min_cooccurrence`` distinct sentences -> ``RELATED_TO``.
* **dxf-mention**: a DXF text/MTEXT annotation names a known entity -> the drawing
  artifact (if ingested) ``REFERENCES`` that entity; rules also run on the text.
* **ifc-structure**: ``IfcRelAggregates`` / ``IfcRelContainedInSpatialStructure``
  -> ``PART_OF`` between ingested IFC elements (explicit in the model file).
* **lightrag** (``rag`` extra): edges of a LightRAG knowledge graph whose two
  endpoints match known entities.

"Known entities" are the curated graph: entities whose stable_key does not start
with an auto-generated ingestion prefix (``concept:``, ``document:``,
``artifact:``, ``ifc:``), matched by name and ``properties.aliases``.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sion_api import models
from sion_core import MissingExtra
from sqlalchemy import select
from sqlalchemy.orm import Session

from sion_ingestion.document_ingest import DOCUMENT_SUFFIXES, DocumentUnreadable, extract_text
from sion_ingestion.graph_export import KNOWN_RELATION_TYPES, normalize_relation_type

EXTRACTOR = "sion-relation-extractor/v1"
AUTO_PREFIXES = ("concept:", "document:", "artifact:", "ifc:", "cand:")
MAX_EVIDENCE_PER_CANDIDATE = 25
MAX_EXCERPT = 500


@dataclass(frozen=True)
class KnownEntity:
    id: Any
    stable_key: str
    name: str


@dataclass(frozen=True)
class TextSpan:
    source_uri: str
    locator: str
    text: str
    kind: str = "document"


@dataclass(frozen=True)
class EvidenceSpan:
    source_uri: str
    locator: str
    excerpt: str
    rule: str
    kind: str


@dataclass
class Proposal:
    source_key: str
    target_key: str
    relation_type_id: str
    rule: str
    confidence: float
    evidence: list[EvidenceSpan] = field(default_factory=list)
    model: str | None = None

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.source_key, self.relation_type_id, self.target_key)


# --------------------------------------------------------------------------- gazetteer


class Gazetteer:
    """Longest-match, non-overlapping entity-name matcher (Latin case-insensitive)."""

    def __init__(self, entities: Iterable[tuple[KnownEntity, list[str]]]) -> None:
        self.entities: dict[str, KnownEntity] = {}
        surface: dict[str, str] = {}
        for entity, names in entities:
            self.entities[entity.stable_key] = entity
            for name in names:
                cleaned = (name or "").strip()
                if len(cleaned) < 2 or (cleaned.isascii() and len(cleaned) < 3):
                    continue
                surface.setdefault(cleaned.casefold(), entity.stable_key)
        self._surface = surface
        if surface:
            parts = sorted(surface, key=len, reverse=True)
            alternation = "|".join(re.escape(p) for p in parts)
            self._pattern = re.compile(rf"(?<![0-9A-Za-z가-힣])(?:{alternation})(?![0-9A-Za-z])", re.IGNORECASE)
        else:
            self._pattern = None

    def __len__(self) -> int:
        return len(self.entities)

    def find(self, text: str) -> list[tuple[int, int, str]]:
        if self._pattern is None:
            return []
        hits = []
        for match in self._pattern.finditer(text):
            key = self._surface.get(match.group(0).casefold())
            if key is not None:
                hits.append((match.start(), match.end(), key))
        return hits

    def lookup(self, name: str) -> str | None:
        return self._surface.get((name or "").strip().casefold())


def build_gazetteer(session: Session, *, exclude_prefixes: tuple[str, ...] = AUTO_PREFIXES) -> Gazetteer:
    rows = []
    for entity in session.scalars(select(models.Entity)):
        if entity.stable_key.startswith(exclude_prefixes):
            continue
        aliases = entity.properties.get("aliases") if isinstance(entity.properties, dict) else None
        names = [entity.name] + [a for a in (aliases or []) if isinstance(a, str)]
        rows.append((KnownEntity(entity.id, entity.stable_key, entity.name), names))
    return Gazetteer(rows)


# --------------------------------------------------------------------------- rules

_EN_FORWARD = [
    (r"(?:also\s+)?(?:uses|utilizes|utilises|relies\s+on|calls|invokes|consumes)", "USES"),
    (r"(?:also\s+)?(?:depends\s+on|requires|needs)", "DEPENDS_ON"),
    (r"(?:is|are)\s+(?:a\s+)?(?:part|component|module|member)\s+of|belongs\s+to|(?:is|are)\s+contained\s+in", "PART_OF"),
    (r"(?:also\s+)?(?:produces|generates|creates|outputs|emits)", "PRODUCES"),
    (r"(?:is|are)\s+(?:derived|generated|built)\s+from|derives\s+from|(?:is|are)\s+based\s+on", "DERIVED_FROM"),
    (r"(?:references|refers\s+to|cites)", "REFERENCES"),
    (r"(?:implements|realizes|realises)", "IMPLEMENTS"),
    (r"(?:supports|enables|feeds|serves)", "SUPPORTS"),
    (r"(?:validates|verifies|checks)", "VALIDATES"),
    (r"(?:connects\s+to|integrates\s+with|(?:is|are)\s+connected\s+to)", "CONNECTS_TO"),
    (r"supersedes|replaces", "SUPERSEDES"),
]
_EN_REVERSE = [
    (r"(?:is|are)\s+used\s+by", "USES"),
    (r"(?:is|are)\s+(?:produced|generated|created)\s+by", "PRODUCES"),
    (r"(?:is|are)\s+(?:validated|verified|checked)\s+by", "VALIDATES"),
    (r"(?:is|are)\s+supported\s+by", "SUPPORTS"),
    (r"(?:is|are)\s+referenced\s+by", "REFERENCES"),
    (r"(?:is|are)\s+implemented\s+by", "IMPLEMENTS"),
    (r"contains|includes|consists\s+of|comprises", "PART_OF"),
]
_FILLER = r"(?:\s+(?:the|a|an|directly|also|then))*"
_EN_RULES = [
    (re.compile(rf"^\s*(?:,\s*which\s+)?{p}{_FILLER}\s*$", re.IGNORECASE), t, "forward") for p, t in _EN_FORWARD
] + [(re.compile(rf"^\s*{p}{_FILLER}\s*$", re.IGNORECASE), t, "reverse") for p, t in _EN_REVERSE]

# Korean: "A(은|는|이|가) B(을|를|에|에서|의|로) <verb>"
_KO_SUBJECT = re.compile(r"^\s*(?:은|는|이|가|도)?\s*$")
_KO_RULES = [
    (re.compile(r"^\s*(?:을|를)\s*(?:사용|활용|이용|호출)"), "USES", "forward"),
    (re.compile(r"^\s*(?:에|에게)\s*의존"), "DEPENDS_ON", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*(?:필요로)"), "DEPENDS_ON", "forward"),
    (re.compile(r"^\s*의\s*(?:일부|구성\s*요소|하위)"), "PART_OF", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*(?:포함|구성)"), "PART_OF", "reverse"),
    (re.compile(r"^\s*(?:을|를)\s*(?:생성|산출|생산|출력|만든|만들)"), "PRODUCES", "forward"),
    (re.compile(r"^\s*(?:에서|으로부터|로부터)\s*(?:파생|생성|유도|변환)"), "DERIVED_FROM", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*기반으로"), "DERIVED_FROM", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*참조"), "REFERENCES", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*구현"), "IMPLEMENTS", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*(?:지원|뒷받침)"), "SUPPORTS", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*(?:검증|확인|점검)"), "VALIDATES", "forward"),
    (re.compile(r"^\s*(?:와|과|에)\s*연결"), "CONNECTS_TO", "forward"),
    (re.compile(r"^\s*(?:을|를)\s*대체"), "SUPERSEDES", "forward"),
]
_KO_PART_OF_IN = re.compile(r"^\s*에\s*(?:속|포함)")
_ARROW = re.compile(r"^\s*(?:-+>|→|=>|⟶)\s*$")
_SENTENCE = re.compile(r"(?<=[.!?。])\s+")


def match_rule(between: str, after: str) -> tuple[str, str, str] | None:
    """Return (relation_type, direction, rule_name) for the text between/after two mentions."""
    if len(between) <= 60:
        for pattern, relation, direction in _EN_RULES:
            if pattern.match(between):
                return relation, direction, f"en:{relation.lower()}:{direction}"
        if _ARROW.match(between):
            return "RELATED_TO", "forward", "arrow"
    if _KO_SUBJECT.match(between):
        if _KO_PART_OF_IN.match(after):
            return "PART_OF", "forward", "ko:part_of:forward"
        for pattern, relation, direction in _KO_RULES:
            if pattern.match(after[:30]):
                return relation, direction, f"ko:{relation.lower()}:{direction}"
    return None


def _sentences(span: TextSpan) -> Iterable[tuple[str, str]]:
    for line_no, line in enumerate(span.text.splitlines(), start=1):
        offset = 0
        for sentence in _SENTENCE.split(line):
            start = line.find(sentence, offset)
            offset = start + len(sentence)
            if sentence.strip():
                yield sentence, f"{span.locator}line:{line_no}:{start}-{offset}"


def propose_from_spans(
    spans: Iterable[TextSpan],
    gazetteer: Gazetteer,
    *,
    min_cooccurrence: int = 2,
    include_cooccurrence: bool = True,
) -> list[Proposal]:
    proposals: dict[tuple[str, str, str], Proposal] = {}
    cooc: dict[tuple[str, str], list[EvidenceSpan]] = defaultdict(list)

    def add(source: str, target: str, relation: str, rule: str, base: float, evidence: EvidenceSpan) -> None:
        if source == target:
            return
        key = (source, relation, target)
        proposal = proposals.get(key)
        if proposal is None:
            proposal = proposals[key] = Proposal(source, target, relation, rule, base)
        if all((e.source_uri, e.locator) != (evidence.source_uri, evidence.locator) for e in proposal.evidence):
            proposal.evidence.append(evidence)

    for span in spans:
        for sentence, locator in _sentences(span):
            hits = gazetteer.find(sentence)
            # collapse repeated mentions of the same entity next to each other
            for left, right in zip(hits, hits[1:]):
                a_start, a_end, a_key = left
                b_start, b_end, b_key = right
                if a_key == b_key:
                    continue
                between = sentence[a_end:b_start]
                after = sentence[b_end:]
                rule = match_rule(between, after)
                evidence = EvidenceSpan(span.source_uri, locator, sentence.strip()[:MAX_EXCERPT], rule[2] if rule else "co-occurrence", span.kind)
                if rule:
                    relation, direction, name = rule
                    source, target = (a_key, b_key) if direction == "forward" else (b_key, a_key)
                    add(source, target, relation, name, 0.35 if name == "arrow" else 0.6, evidence)
            if include_cooccurrence:
                keys = sorted({key for *_, key in hits})
                for i, a in enumerate(keys):
                    for b in keys[i + 1 :]:
                        cooc[(a, b)].append(EvidenceSpan(span.source_uri, locator, sentence.strip()[:MAX_EXCERPT], "co-occurrence", span.kind))

    ruled_pairs = {frozenset((p.source_key, p.target_key)) for p in proposals.values()}
    for (a, b), evidence in cooc.items():
        distinct = {(e.source_uri, e.locator): e for e in evidence}
        if frozenset((a, b)) in ruled_pairs or len(distinct) < min_cooccurrence:
            continue
        proposal = Proposal(a, b, "RELATED_TO", "co-occurrence", 0.0, list(distinct.values()))
        proposals[proposal.triple] = proposal

    for proposal in proposals.values():
        support = len(proposal.evidence)
        if proposal.rule == "co-occurrence":
            proposal.confidence = round(min(0.5, 0.15 + 0.05 * support), 3)
        else:
            proposal.confidence = round(min(0.85, proposal.confidence + 0.05 * (support - 1)), 3)
    return sorted(proposals.values(), key=lambda p: (-p.confidence, p.triple))


# --------------------------------------------------------------------------- file sources


def _file_uri(path: Path) -> str:
    return f"file:///{path.resolve().as_posix().lstrip('/')}"


def document_spans(path: Path) -> list[TextSpan]:
    content = extract_text(path)
    return [TextSpan(_file_uri(path), "", content.text, "document")]


def dxf_sources(path: Path, gazetteer: Gazetteer, session: Session) -> tuple[list[TextSpan], list[Proposal], list[str]]:
    from sion_cad import reader

    notes: list[str] = []
    result = reader.read_entities(path)
    uri = _file_uri(path)
    spans = [
        TextSpan(uri, f"dxf:{index}:handle:{item.get('handle') or '-'}:", str(item.get("name") or ""), "dxf")
        for index, item in enumerate(result.items)
        if item.get("kind") == "annotation" and item.get("name")
    ]
    drawing_key = "artifact:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    drawing = session.scalar(select(models.Entity).where(models.Entity.stable_key == drawing_key))
    proposals: list[Proposal] = []
    if drawing is None:
        notes.append(f"{path.name}: drawing not ingested (POST /api/v1/ingest/dxf first) - no drawing REFERENCES candidates")
        return spans, proposals, notes
    by_target: dict[str, Proposal] = {}
    for span in spans:
        for _start, _end, key in gazetteer.find(span.text):
            proposal = by_target.setdefault(key, Proposal(drawing_key, key, "REFERENCES", "dxf-mention", 0.55))
            proposal.evidence.append(EvidenceSpan(uri, span.locator.rstrip(":"), span.text[:MAX_EXCERPT], "dxf-mention", "dxf"))
    for proposal in by_target.values():
        proposal.confidence = round(min(0.8, 0.55 + 0.05 * (len(proposal.evidence) - 1)), 3)
        proposals.append(proposal)
    return spans, proposals, notes


_STEP = re.compile(r"#(\d+)\s*=\s*(IFC[A-Z0-9_]+)\s*\((.*?)\)\s*;", re.DOTALL)
_REF = re.compile(r"#(\d+)")


def ifc_structure_proposals(path: Path, session: Session) -> tuple[list[Proposal], list[str]]:
    """PART_OF candidates from the explicit IFC decomposition/containment relationships."""
    from sion_bim.ifc import _split_args, _string

    notes: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    model_key = "artifact:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    global_ids: dict[str, str] = {}
    rels: list[tuple[str, str, list[str]]] = []
    for match in _STEP.finditer(text):
        step_id, ifc_class, raw = match.group(1), match.group(2), match.group(3)
        args = _split_args(raw)
        if ifc_class in {"IFCRELAGGREGATES", "IFCRELNESTS"} and len(args) >= 6:
            parent = _REF.findall(args[4])
            rels.append((step_id, parent[0] if parent else "", _REF.findall(args[5])))
        elif ifc_class == "IFCRELCONTAINEDINSPATIALSTRUCTURE" and len(args) >= 6:
            parent = _REF.findall(args[5])
            rels.append((step_id, parent[0] if parent else "", _REF.findall(args[4])))
        elif args:
            gid = _string(args[0])
            if gid:
                global_ids[step_id] = gid
    existing = {
        row.stable_key
        for row in session.scalars(select(models.Entity).where(models.Entity.stable_key.like(f"ifc:{model_key}:%")))
    }
    if not existing:
        notes.append(f"{path.name}: model not ingested (POST /api/v1/ingest/ifc first) - no IFC structure candidates")
        return [], notes
    proposals: list[Proposal] = []
    uri = _file_uri(path)
    for rel_id, parent, children in rels:
        parent_key = f"ifc:{model_key}:{global_ids.get(parent, '')}"
        if parent_key not in existing:
            continue
        for child in children:
            child_key = f"ifc:{model_key}:{global_ids.get(child, '')}"
            if child_key not in existing or child_key == parent_key:
                continue
            proposals.append(
                Proposal(
                    child_key,
                    parent_key,
                    "PART_OF",
                    "ifc-structure",
                    0.8,
                    [EvidenceSpan(uri, f"ifc:#{rel_id}", f"#{rel_id}: #{child} -> #{parent}", "ifc-structure", "ifc")],
                )
            )
    return proposals, notes


# --------------------------------------------------------------------------- LightRAG


def proposals_from_lightrag(kg: Any, gazetteer: Gazetteer, *, workspace: str = "sion", model: str | None = None) -> tuple[list[Proposal], list[str]]:
    """Convert a LightRAG ``KnowledgeGraph`` (object or dict) into candidates.

    Only edges whose two endpoints name known entities are kept; LightRAG's own
    extracted entities are never added to the canonical graph here.
    """
    data = kg.model_dump() if hasattr(kg, "model_dump") else dict(kg)
    names: dict[str, str] = {}
    for node in data.get("nodes") or []:
        props = node.get("properties") or {}
        names[str(node.get("id"))] = str(props.get("entity_id") or node.get("id"))
    proposals: dict[tuple[str, str, str], Proposal] = {}
    skipped = 0
    for edge in data.get("edges") or []:
        props = edge.get("properties") or {}
        source = gazetteer.lookup(names.get(str(edge.get("source")), str(edge.get("source"))))
        target = gazetteer.lookup(names.get(str(edge.get("target")), str(edge.get("target"))))
        if source is None or target is None or source == target:
            skipped += 1
            continue
        relation = "RELATED_TO"
        for keyword in re.split(r"[,;/]", str(props.get("keywords") or edge.get("type") or "")):
            mapped, _ = normalize_relation_type(keyword.strip())
            if keyword.strip() and mapped != "RELATED_TO" and mapped in KNOWN_RELATION_TYPES:
                relation = mapped
                break
        locator = f"lightrag:{edge.get('id') or ''}:chunks:{props.get('source_id') or '-'}"
        file_path = props.get("file_path")
        evidence = EvidenceSpan(
            f"lightrag://{workspace}" + (f"/{file_path}" if file_path else ""),
            locator,
            str(props.get("description") or "")[:MAX_EXCERPT],
            "lightrag",
            "lightrag",
        )
        key = (source, relation, target)
        proposal = proposals.setdefault(key, Proposal(source, target, relation, "lightrag", 0.45, model=model))
        proposal.evidence.append(evidence)
    notes = [f"lightrag: {skipped} edges skipped (endpoint not a known entity)"] if skipped else []
    return list(proposals.values()), notes


async def lightrag_knowledge_graph(rag: Any, *, max_nodes: int = 1000) -> Any:
    """Fetch the whole LightRAG graph (``node_label='*'``) from a started engine."""
    result = rag.get_knowledge_graph(node_label="*", max_depth=3, max_nodes=max_nodes)
    return await result if inspect.isawaitable(result) else result


# --------------------------------------------------------------------------- storage


def candidate_stable_key(source_key: str, relation: str, target_key: str) -> str:
    key = f"cand:{source_key}:{relation}:{target_key}"
    if len(key) <= 700:
        return key
    return "cand:sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def store_proposals(session: Session, proposals: Iterable[Proposal], *, extractor: str = EXTRACTOR) -> dict[str, Any]:
    created = updated = evidence_created = 0
    skipped: list[dict[str, str]] = []
    keys = set()
    proposals = list(proposals)
    for p in proposals:
        keys.update((p.source_key, p.target_key))
    entities = {
        row.stable_key: row
        for row in session.scalars(select(models.Entity).where(models.Entity.stable_key.in_(sorted(keys))))
    } if keys else {}
    known_types = {row.id for row in session.scalars(select(models.RelationType))}
    candidate_ids: list[str] = []

    for proposal in proposals:
        source = entities.get(proposal.source_key)
        target = entities.get(proposal.target_key)
        label = f"{proposal.source_key} -{proposal.relation_type_id}-> {proposal.target_key}"
        if source is None or target is None:
            skipped.append({"candidate": label, "reason": "unknown endpoint"})
            continue
        if proposal.relation_type_id not in known_types:
            skipped.append({"candidate": label, "reason": f"unknown relation type {proposal.relation_type_id}"})
            continue
        if source.id == target.id and proposal.relation_type_id != "RELATED_TO":
            skipped.append({"candidate": label, "reason": "typed self-loop"})
            continue
        existing_fact = session.scalar(
            select(models.Relation).where(
                models.Relation.source_entity_id == source.id,
                models.Relation.target_entity_id == target.id,
                models.Relation.relation_type_id == proposal.relation_type_id,
            )
        )
        if existing_fact is not None and not (existing_fact.properties or {}).get("candidate"):
            skipped.append({"candidate": label, "reason": "relation already exists"})
            continue
        stable_key = candidate_stable_key(proposal.source_key, proposal.relation_type_id, proposal.target_key)
        row = existing_fact or session.scalar(select(models.Relation).where(models.Relation.stable_key == stable_key))
        if row is not None and row.verification_state != "unverified":
            skipped.append({"candidate": label, "reason": f"already reviewed ({row.verification_state})"})
            continue
        if row is None:
            row = models.Relation(
                stable_key=stable_key,
                source_entity_id=source.id,
                target_entity_id=target.id,
                relation_type_id=proposal.relation_type_id,
                confidence=proposal.confidence,
                verification_state="unverified",
                source_kind="inferred",
                properties={
                    "candidate": True,
                    "extractor": extractor,
                    "rules": [proposal.rule],
                    "support": 0,
                    **({"model": proposal.model} if proposal.model else {}),
                },
            )
            session.add(row)
            session.flush()
            created += 1
        else:
            updated += 1
        have = {
            (e.source_uri, e.source_locator)
            for e in session.scalars(select(models.Evidence).where(models.Evidence.relation_id == row.id))
        }
        for span in proposal.evidence:
            if len(have) >= MAX_EVIDENCE_PER_CANDIDATE:
                break
            if (span.source_uri, span.locator) in have:
                continue
            have.add((span.source_uri, span.locator))
            session.add(
                models.Evidence(
                    relation_id=row.id,
                    source_uri=span.source_uri,
                    source_locator=span.locator,
                    excerpt_hash=hashlib.sha256(span.excerpt.encode("utf-8")).hexdigest(),
                    confidence=proposal.confidence,
                    verification_state="unverified",
                    extractor=extractor,
                    model=proposal.model,
                    properties={"excerpt": span.excerpt, "rule": span.rule, "kind": span.kind},
                )
            )
            evidence_created += 1
        properties = dict(row.properties or {})
        rules = list(properties.get("rules") or [])
        if proposal.rule not in rules:
            rules.append(proposal.rule)
        properties.update({"candidate": True, "rules": rules, "support": len(have)})
        row.properties = properties
        row.confidence = max(row.confidence or 0.0, proposal.confidence)
        candidate_ids.append(str(row.id))
    session.commit()
    return {
        "candidates_created": created,
        "candidates_updated": updated,
        "evidence_created": evidence_created,
        "skipped": skipped,
        "candidate_ids": candidate_ids,
        "verification_state": "unverified",
    }


def extract_relation_candidates(
    session: Session,
    paths: list[Path],
    *,
    min_cooccurrence: int = 2,
    include_cooccurrence: bool = True,
) -> dict[str, Any]:
    """Run every applicable extractor on ``paths`` and store candidates."""
    gazetteer = build_gazetteer(session)
    spans: list[TextSpan] = []
    direct: list[Proposal] = []
    notes: list[str] = []
    files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    for path in paths:
        suffix = path.suffix.lower()
        if not path.is_file():
            skipped_files.append({"path": str(path), "reason": "not a file"})
            continue
        try:
            if suffix == ".dxf":
                dxf_spans, dxf_props, dxf_notes = dxf_sources(path, gazetteer, session)
                spans += dxf_spans
                direct += dxf_props
                notes += dxf_notes
            elif suffix == ".ifc":
                ifc_props, ifc_notes = ifc_structure_proposals(path, session)
                direct += ifc_props
                notes += ifc_notes
            elif suffix in DOCUMENT_SUFFIXES:
                spans += document_spans(path)
            else:
                skipped_files.append({"path": str(path), "reason": f"unsupported type {suffix or '(none)'}"})
                continue
        except (MissingExtra, DocumentUnreadable, OSError, ValueError) as exc:
            skipped_files.append({"path": str(path), "reason": str(exc)})
            continue
        files.append(str(path))
    if not len(gazetteer):
        notes.append("no curated entities to match yet; import a map export or create entities first")
    proposals = propose_from_spans(spans, gazetteer, min_cooccurrence=min_cooccurrence, include_cooccurrence=include_cooccurrence)
    stored = store_proposals(session, direct + proposals)
    rule_counts: dict[str, int] = defaultdict(int)
    for proposal in direct + proposals:
        rule_counts[proposal.rule.split(":")[0]] += 1
    return {
        "files": files,
        "skipped_files": skipped_files,
        "known_entities": len(gazetteer),
        "proposals": len(direct) + len(proposals),
        "proposals_by_extractor": dict(sorted(rule_counts.items())),
        "notes": notes,
        **stored,
    }
