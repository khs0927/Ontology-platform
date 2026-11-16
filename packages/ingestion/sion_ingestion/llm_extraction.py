"""Ontology-constrained relation extraction with a language model.

The model may only answer in the shape of the *live* ontology: its JSON schema is generated from
``entity_types`` and ``relation_types`` in the database (the canonical ontology), so an unknown
relation or entity type is a schema error, not a row. Everything the model says then passes four
deterministic gates before it is stored, and what survives is still only a review candidate:

1. **Schema** - the reply is validated by a Pydantic model built from the ontology (``Literal``
   enums); one retry with the validation error, then the chunk is reported as failed.
2. **Grounding** - the quoted evidence must occur verbatim (whitespace-normalised) in the chunk,
   and both endpoint names must occur in it. Paraphrases and hallucinated quotes are dropped.
3. **Resolution** - both endpoints must be curated entities (name or alias, through the same
   gazetteer as the rule extractor). Unknown names come back as ``entity_suggestions`` for a
   person to create; the extractor never invents canonical entities.
4. **Domain/range** - when a relation type declares ``source_type_id``/``target_type_id``, the
   stored entity types (not the model's claim) must match, subclasses included
   (``entity_types.parent_type_id``). This is the SHACL ``sh:class`` rule applied before insert.

Survivors go through :func:`sion_ingestion.relation_extraction.store_proposals` like every other
extractor: ``unverified`` relations with ``properties.candidate = True`` and one evidence row per
quote, decided in ``/review``.

Any OpenAI-compatible chat endpoint with JSON-schema structured output works (OpenAI, vLLM,
Ollama, LM Studio, or a gateway in front of another provider): set ``SION_EXTRACT_BASE_URL`` and
``SION_EXTRACT_MODEL``. Nothing is called when they are unset.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model
from sion_api import models
from sqlalchemy import select
from sqlalchemy.orm import Session

from sion_ingestion.document_ingest import DocumentUnreadable, extract_text
from sion_ingestion.relation_extraction import (
    EvidenceSpan,
    Gazetteer,
    Proposal,
    build_gazetteer,
    store_proposals,
)

EXTRACTOR = "sion-llm-extractor/v1"
BASE_CONFIDENCE = 0.5
MAX_QUOTE = 300
# Structural edges written by importers, never proposed from prose.
NON_EXTRACTABLE = frozenset({"EXTRACTED_FROM", "EVIDENCED_BY", "VERSION_OF"})

SYSTEM_PROMPT = """You extract a knowledge graph from one passage for a curated ontology.
Rules:
- Use only the entity types and relation types in the JSON schema. If nothing fits, return empty lists.
- A relation needs an explicit statement in the passage. Do not infer, generalise or use outside knowledge.
- "evidence" must be an exact, contiguous quote from the passage (at most 300 characters) that states the relation.
- Use entity names exactly as written in the passage.
- Direction matters: "source RELATION target" must read as a true sentence.
Relation types:
{relations}
Entity types: {entities}"""


# --------------------------------------------------------------------------- ontology


@dataclass(frozen=True)
class RelationSpec:
    id: str
    label: str
    source_type: str | None = None
    target_type: str | None = None
    symmetric: bool = False


@dataclass
class OntologySpec:
    entity_parents: dict[str, str | None]
    relations: dict[str, RelationSpec]

    @classmethod
    def from_session(cls, session: Session) -> OntologySpec:
        parents = {row.id: row.parent_type_id for row in session.scalars(select(models.EntityType))}
        relations = {
            row.id: RelationSpec(row.id, row.label, row.source_type_id, row.target_type_id, bool(row.is_symmetric))
            for row in session.scalars(select(models.RelationType))
            if row.id not in NON_EXTRACTABLE
        }
        return cls(parents, relations)

    def is_a(self, type_id: str | None, ancestor: str) -> bool:
        seen: set[str] = set()
        while type_id and type_id not in seen:
            if type_id == ancestor:
                return True
            seen.add(type_id)
            type_id = self.entity_parents.get(type_id)
        return False

    def violation(self, relation: str, source_type: str | None, target_type: str | None) -> str | None:
        spec = self.relations.get(relation)
        if spec is None:
            return f"relation type {relation} is not extractable"
        if spec.source_type and not self.is_a(source_type, spec.source_type):
            return f"{relation} needs a {spec.source_type} source, got {source_type}"
        if spec.target_type and not self.is_a(target_type, spec.target_type):
            return f"{relation} needs a {spec.target_type} target, got {target_type}"
        return None


def response_model(spec: OntologySpec) -> type[BaseModel]:
    """Pydantic model of an extraction reply whose enums are the ontology's types."""
    entity_type = Literal[tuple(sorted(spec.entity_parents))]  # type: ignore[valid-type]
    relation_type = Literal[tuple(sorted(spec.relations))]  # type: ignore[valid-type]
    strict = ConfigDict(extra="forbid")
    mention = create_model(
        "Mention", __config__=strict,
        name=(str, Field(min_length=1, max_length=300)),
        type=(entity_type, ...),
    )
    triple = create_model(
        "Triple", __config__=strict,
        source=(str, Field(min_length=1, max_length=300)),
        relation=(relation_type, ...),
        target=(str, Field(min_length=1, max_length=300)),
        evidence=(str, Field(min_length=1, max_length=MAX_QUOTE * 2)),
    )
    return create_model(
        "Extraction", __config__=strict,
        entities=(list[mention], ...),
        relations=(list[triple], ...),
    )


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """JSON schema accepted by strict structured-output modes (no length keywords, all required)."""
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: walk(v) for k, v in node.items() if k not in {"minLength", "maxLength", "title"}}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


# --------------------------------------------------------------------------- model endpoint


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 120.0
    chunk_chars: int = 4000
    max_chunks: int = 200

    @classmethod
    def from_env(cls) -> LlmConfig | None:
        base_url, model = os.getenv("SION_EXTRACT_BASE_URL"), os.getenv("SION_EXTRACT_MODEL")
        if not base_url or not model:
            return None
        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=os.getenv("SION_EXTRACT_API_KEY") or None,
            timeout=float(os.getenv("SION_EXTRACT_TIMEOUT_SECONDS", "120")),
            chunk_chars=int(os.getenv("SION_EXTRACT_CHUNK_CHARS", "4000")),
            max_chunks=int(os.getenv("SION_EXTRACT_MAX_CHUNKS", "200")),
        )


class ExtractionFailed(RuntimeError):
    pass


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Pack paragraphs into chunks of at most ``max_chars`` (a longer paragraph is split hard)."""
    chunks: list[str] = []
    current = ""
    for para in (p.strip() for p in re.split(r"\n\s*\n|\n(?=#)", text or "")):
        if not para:
            continue
        while len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        if current and len(current) + 2 + len(para) > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def _prompt(spec: OntologySpec) -> str:
    lines = []
    for r in sorted(spec.relations.values(), key=lambda r: r.id):
        domain = f" ({r.source_type or 'any'} -> {r.target_type or 'any'})" if r.source_type or r.target_type else ""
        lines.append(f"- {r.id}: {r.label}{domain}")
    return SYSTEM_PROMPT.format(relations="\n".join(lines), entities=", ".join(sorted(spec.entity_parents)))


def call_model(chunk: str, spec: OntologySpec, config: LlmConfig, *, transport=None) -> BaseModel:
    """One schema-constrained completion, validated; one retry on a schema error."""
    import httpx

    reply_model = response_model(spec)
    schema = _strict_schema(reply_model.model_json_schema())
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _prompt(spec)},
        {"role": "user", "content": chunk},
    ]
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    last_error = ""
    with httpx.Client(timeout=config.timeout, transport=transport, headers=headers) as client:
        for _attempt in range(2):
            payload = {
                "model": config.model,
                "temperature": 0,
                "messages": messages,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "extraction", "schema": schema, "strict": True}},
            }
            try:
                response = client.post(f"{config.base_url}/chat/completions", json=payload)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"] or ""
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                raise ExtractionFailed(f"model endpoint failed ({type(exc).__name__}: {exc})") from exc
            try:
                return reply_model.model_validate_json(content)
            except ValidationError as exc:
                last_error = str(exc)[:1500]
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That reply does not match the schema:\n{last_error}\nReply again with valid JSON only."},
                ]
    raise ExtractionFailed(f"reply did not match the ontology schema: {last_error}")


# --------------------------------------------------------------------------- gates


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").split()).casefold()


def grounded(quote: str, chunk: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(chunk)


@dataclass
class ChunkOutcome:
    proposals: list[Proposal] = field(default_factory=list)
    suggestions: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejected: list[dict[str, str]] = field(default_factory=list)


def gate(reply: BaseModel, chunk: str, *, source_uri: str, locator: str, spec: OntologySpec,
         gazetteer: Gazetteer, entity_types: dict[str, str], model: str) -> ChunkOutcome:
    """Apply grounding, resolution and domain/range gates to one validated reply."""
    out = ChunkOutcome()
    claimed = {_norm(m.name): m.type for m in reply.entities}
    chunk_norm = _norm(chunk)
    for t in reply.relations:
        label = f"{t.source} -{t.relation}-> {t.target}"
        quote = " ".join(t.evidence.split())[:MAX_QUOTE]
        if not grounded(t.evidence, chunk):
            out.rejected.append({"candidate": label, "reason": "evidence is not a quote from the passage"})
            continue
        if _norm(t.source) not in chunk_norm or _norm(t.target) not in chunk_norm:
            out.rejected.append({"candidate": label, "reason": "endpoint name not in the passage"})
            continue
        keys = []
        for name in (t.source, t.target):
            key = gazetteer.lookup(name)
            if key is None:
                suggestion = out.suggestions.setdefault(_norm(name), {
                    "name": name.strip(), "type": claimed.get(_norm(name)), "evidence": [],
                })
                if len(suggestion["evidence"]) < 3:
                    suggestion["evidence"].append({"source_uri": source_uri, "locator": locator, "excerpt": quote})
            keys.append(key)
        if None in keys:
            out.rejected.append({"candidate": label, "reason": "endpoint is not a curated entity"})
            continue
        source_key, target_key = keys
        if source_key == target_key:
            out.rejected.append({"candidate": label, "reason": "self-loop"})
            continue
        problem = spec.violation(t.relation, entity_types.get(source_key), entity_types.get(target_key))
        if problem:
            out.rejected.append({"candidate": label, "reason": f"domain/range: {problem}"})
            continue
        if spec.relations[t.relation].symmetric and target_key < source_key:
            source_key, target_key = target_key, source_key
        out.proposals.append(Proposal(
            source_key, target_key, t.relation, f"llm:{t.relation.lower()}", BASE_CONFIDENCE,
            [EvidenceSpan(source_uri, locator, quote, f"llm:{t.relation.lower()}", "document")], model=model,
        ))
    return out


# --------------------------------------------------------------------------- pipeline


def _merge(proposals: list[Proposal]) -> list[Proposal]:
    merged: dict[tuple[str, str, str], Proposal] = {}
    for p in proposals:
        existing = merged.get(p.triple)
        if existing is None:
            merged[p.triple] = p
            continue
        for e in p.evidence:
            if all((x.source_uri, x.locator) != (e.source_uri, e.locator) for x in existing.evidence):
                existing.evidence.append(e)
    for p in merged.values():  # more independent quotes, more confidence; capped below rule-backed edges
        p.confidence = round(min(0.75, BASE_CONFIDENCE + 0.05 * (len(p.evidence) - 1)), 3)
    return sorted(merged.values(), key=lambda p: (-p.confidence, p.triple))


def extract_with_llm(session: Session, paths: list[Path], config: LlmConfig, *, transport=None) -> dict[str, Any]:
    """Read documents, extract with the model, gate, and store review candidates."""
    from sion_core import MissingExtra

    spec = OntologySpec.from_session(session)
    gazetteer = build_gazetteer(session)
    entity_types = {key: row for key, row in session.execute(
        select(models.Entity.stable_key, models.Entity.entity_type_id)).all()}
    proposals: list[Proposal] = []
    suggestions: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, str]] = []
    failed_chunks: list[dict[str, str]] = []
    files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    chunks_sent = 0
    for path in paths:
        if not path.is_file():
            skipped_files.append({"path": str(path), "reason": "not a file"})
            continue
        try:
            content = extract_text(path)
        except (MissingExtra, DocumentUnreadable, OSError) as exc:
            skipped_files.append({"path": str(path), "reason": str(exc)})
            continue
        files.append(str(path))
        uri = f"file:///{path.resolve().as_posix().lstrip('/')}"
        for index, chunk in enumerate(chunk_text(content.text, config.chunk_chars)):
            if chunks_sent >= config.max_chunks:
                failed_chunks.append({"path": str(path), "chunk": str(index), "reason": "max_chunks reached"})
                break
            chunks_sent += 1
            locator = f"chunk:{index}"
            try:
                reply = call_model(chunk, spec, config, transport=transport)
            except ExtractionFailed as exc:
                failed_chunks.append({"path": str(path), "chunk": str(index), "reason": str(exc)})
                continue
            outcome = gate(reply, chunk, source_uri=uri, locator=locator, spec=spec, gazetteer=gazetteer,
                           entity_types=entity_types, model=config.model)
            proposals += outcome.proposals
            rejected += outcome.rejected
            for key, suggestion in outcome.suggestions.items():
                merged = suggestions.setdefault(key, {**suggestion, "evidence": []})
                merged["evidence"] = (merged["evidence"] + suggestion["evidence"])[:3]
    merged = _merge(proposals)
    stored = store_proposals(session, merged, extractor=EXTRACTOR)
    return {
        "model": config.model,
        "files": files,
        "skipped_files": skipped_files,
        "chunks": chunks_sent,
        "failed_chunks": failed_chunks,
        "proposals": len(merged),
        "rejected": rejected,
        "entity_suggestions": sorted(suggestions.values(), key=lambda s: s["name"]),
        **stored,
    }


def schema_preview(session: Session) -> dict[str, Any]:
    """The JSON schema the model is held to, for inspection (``GET /api/v1/extract/llm/schema``)."""
    spec = OntologySpec.from_session(session)
    return {"schema": _strict_schema(response_model(spec).model_json_schema()), "system_prompt": _prompt(spec),
            "configured": LlmConfig.from_env() is not None}


__all__ = ["EXTRACTOR", "LlmConfig", "OntologySpec", "chunk_text", "extract_with_llm", "gate", "grounded",
           "response_model", "schema_preview"]
