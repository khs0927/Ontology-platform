"""Law-article knowledge store: ingestion + search (first slice of the law-knowledge consolidation).

Consolidates the four separate law lookups (korean-building-law-monorepo RAG, korean-law-gpt-actions
resolver, building-regulation-gateway evidence, site-pipeline-mcp knowledge graph) behind one
canonical article table. See docs/regulation/law-knowledge-plan.md.

Design rules
* One row per (law_id, article_key, effective_from): amendments are new versions, never overwrites.
* Ingestion is idempotent: same key + same content hash -> ``unchanged``; same key + new hash -> 409
  (a changed text under the same effective date is a source error that a human must look at).
* Search is portable (SQLite and PostgreSQL) lexical scoring over title + text with an ``as_of``
  filter so callers never get an article that was not in force on the review date.
  Vector/graph retrieval is a later slice.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, Date, DateTime, Index, String, Text, UniqueConstraint, Uuid, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base

ARTICLE_KEY = re.compile(r"^\d{1,4}(?:-\d{1,3})?$")  # "61", "61-2" (제61조의2)
_TOKEN = re.compile(r"[0-9A-Za-z\uac00-\ud7a3]+")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def content_hash(title: str | None, text: str) -> str:
    return "sha256:" + hashlib.sha256(f"{title or ''}\n{normalize_text(text)}".encode()).hexdigest()


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(unicodedata.normalize("NFC", text or ""))]


def article_label(article_key: str) -> str:
    main, _, branch = article_key.partition("-")
    return f"제{main}조" + (f"의{branch}" if branch else "")


def parse_article_key(v: str) -> str:
    """'제61조의2' / '61조의2' / '61-2' -> '61-2'."""
    v = (v or "").strip()
    m = re.fullmatch(r"제?(\d{1,4})조?(?:의(\d{1,3}))?", v)
    if m:
        v = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
    if not ARTICLE_KEY.match(v):
        raise ValueError("article_key must look like '61', '61-2' or '제61조의2'")
    return v


class LawArticle(Base):
    __tablename__ = "law_articles"
    __table_args__ = (
        UniqueConstraint("law_id", "article_key", "effective_from", name="uq_law_article_version"),
        Index("idx_law_articles_law", "law_id", "article_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    law_id: Mapped[str] = mapped_column(String(64), nullable=False)  # 법제처 법령ID or MST
    law_name: Mapped[str] = mapped_column(String(300), nullable=False)
    law_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="act")
    article_key: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    promulgated_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False, default="국가법령정보센터")
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


LAW_KINDS = {"act", "decree", "rule", "ordinance", "notice"}


class LawArticleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    law_id: str = Field(min_length=1, max_length=64)
    law_name: str = Field(min_length=1, max_length=300)
    law_kind: str = "act"
    article_key: str
    title: str | None = None
    text: str = Field(min_length=1)
    effective_from: date
    effective_to: date | None = None
    promulgated_on: date | None = None
    source_url: str | None = None
    publisher: str = "국가법령정보센터"
    refs: list[str] = Field(default_factory=list)

    @field_validator("article_key")
    @classmethod
    def _key(cls, v: str) -> str:
        return parse_article_key(v)

    @field_validator("law_kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in LAW_KINDS:
            raise ValueError(f"law_kind must be one of {sorted(LAW_KINDS)}")
        return v


class LawIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    articles: list[LawArticleIn] = Field(min_length=1, max_length=2000)


def _out(a: LawArticle) -> dict:
    return {
        "id": str(a.id), "law_id": a.law_id, "law_name": a.law_name, "law_kind": a.law_kind,
        "article_key": a.article_key, "article_label": article_label(a.article_key), "title": a.title,
        "text": a.text, "effective_from": a.effective_from.isoformat(),
        "effective_to": a.effective_to.isoformat() if a.effective_to else None,
        "source_url": a.source_url, "publisher": a.publisher, "content_hash": a.content_hash, "refs": a.refs,
    }


def ingest(session: Session, articles: list[LawArticleIn]) -> dict:
    created, unchanged, conflicts = [], [], []
    for item in articles:
        if item.effective_to and item.effective_to < item.effective_from:
            raise HTTPException(422, f"{item.law_name} {item.article_key}: effective_to before effective_from")
        h = content_hash(item.title, item.text)
        existing = session.scalar(select(LawArticle).where(
            LawArticle.law_id == item.law_id, LawArticle.article_key == item.article_key,
            LawArticle.effective_from == item.effective_from))
        key = f"{item.law_id}:{item.article_key}@{item.effective_from.isoformat()}"
        if existing is not None:
            (unchanged if existing.content_hash == h else conflicts).append(key)
            continue
        row = LawArticle(**item.model_dump(exclude={"text"}), text=normalize_text(item.text), content_hash=h)
        session.add(row)
        session.flush()
        created.append(key)
    if conflicts:
        session.rollback()
        raise HTTPException(409, {"detail": "content changed under an existing version", "conflicts": conflicts})
    session.commit()
    return {"created": created, "unchanged": unchanged}


def _score(q: list[str], phrase: str, a: LawArticle) -> float:
    title, body = " ".join(tokens(a.title or "")), " ".join(tokens(a.text))
    s = 0.0
    for t in q:
        s += 3.0 * title.count(t) + min(body.count(t), 5)
    if phrase and phrase in normalize_text(a.text):
        s += 5.0
    return s


def _snippet(text: str, q: list[str], width: int = 200) -> str:
    low = text.lower()
    pos = min((low.find(t) for t in q if low.find(t) >= 0), default=0)
    start = max(0, pos - width // 3)
    return ("…" if start else "") + text[start:start + width] + ("…" if start + width < len(text) else "")


def search(session: Session, q: str, *, law: str | None = None, as_of: date | None = None,
           limit: int = 10) -> dict:
    qt = tokens(q)
    if not qt:
        raise HTTPException(422, "query has no searchable tokens")
    as_of = as_of or date.today()
    stmt = select(LawArticle).where(
        LawArticle.effective_from <= as_of,
        or_(LawArticle.effective_to.is_(None), LawArticle.effective_to >= as_of))
    if law:
        stmt = stmt.where(or_(LawArticle.law_id == law, LawArticle.law_name == law))
    like = [or_(LawArticle.text.ilike(f"%{t}%"), LawArticle.title.ilike(f"%{t}%")) for t in qt]
    stmt = stmt.where(or_(*like))
    rows = list(session.scalars(stmt))
    # keep only the newest version in force per article (a later effective_from supersedes)
    latest: dict[tuple[str, str], LawArticle] = {}
    for a in rows:
        k = (a.law_id, a.article_key)
        if k not in latest or a.effective_from > latest[k].effective_from:
            latest[k] = a
    phrase = normalize_text(q)
    hits = sorted(((_score(qt, phrase, a), a) for a in latest.values()), key=lambda x: (-x[0], x[1].law_name, x[1].article_key))
    return {
        "query": q, "as_of": as_of.isoformat(), "total": len(hits),
        "results": [{**{k: v for k, v in _out(a).items() if k != "text"}, "score": round(s, 3),
                     "snippet": _snippet(a.text, qt),
                     "citation": f"{a.law_name} {article_label(a.article_key)}"} for s, a in hits[:limit]],
    }


def register(app: FastAPI, get_session, read_dep, write_dep) -> None:
    @app.post("/api/v1/law/articles", dependencies=[Depends(write_dep)], status_code=201)
    def law_ingest(payload: LawIngest, session: Session = Depends(get_session)):
        return ingest(session, payload.articles)

    @app.get("/api/v1/law/search", dependencies=[Depends(read_dep)])
    def law_search(q: str = Query(min_length=1, max_length=500), law: str | None = None,
                   as_of: date | None = None, limit: int = Query(10, ge=1, le=50),
                   session: Session = Depends(get_session)):
        return search(session, q, law=law, as_of=as_of, limit=limit)

    @app.get("/api/v1/law/articles/{law_id}/{article_key}", dependencies=[Depends(read_dep)])
    def law_article(law_id: str, article_key: str, as_of: date | None = None,
                    session: Session = Depends(get_session)):
        try:
            key = parse_article_key(article_key)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        as_of = as_of or date.today()
        row = session.scalar(select(LawArticle).where(
            LawArticle.law_id == law_id, LawArticle.article_key == key, LawArticle.effective_from <= as_of,
            or_(LawArticle.effective_to.is_(None), LawArticle.effective_to >= as_of),
        ).order_by(LawArticle.effective_from.desc()).limit(1))
        if row is None:
            raise HTTPException(404, "no version of this article in force on as_of")
        return _out(row)
