"""Cross-references between Korean law articles (law-knowledge slice 3, rule-based).

Korean statutes cite each other in a small, regular grammar, so a rule extractor beats a model here:
it is exact, explainable and free. This module turns article text into references of the form
``"<법령명>:<article_key>"`` (the same identity as ``law_articles.refs`` and the evaluation corpus).

Handled forms (examples from 건축법 시행령):

* ``제80조제1항제1호``                     -> this law, article 80 (항/호 kept as detail)
* ``법 제80조`` / ``영 제5조`` / ``규칙 제3조`` -> the act / decree / rule of the same family
* ``같은 법 제2조``                         -> the law named most recently in this text
* ``이 법`` / ``이 영`` / ``이 규칙``         -> this law
* ``「국토의 계획 및 이용에 관한 법률」 제77조`` -> the named law (``「… 시행령」`` too)
* ``제11조, 제14조 및 제16조``               -> a list inherits the law of its first item
* ``제5조부터 제8조까지``                    -> the range, expanded (at most 20 articles)
* ``별표 1`` / ``[별표 3]``                  -> an appendix of the law: ``<법령명>:별표1``

The article's own heading (``제115조의3(이행강제금…)``) is not a reference. A reference whose
target is not in the store stays in the list: absence from the corpus is not evidence that the
cited article does not exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FAMILY_SUFFIXES = (" 시행령", " 시행규칙")
MAX_RANGE = 20

_ARTICLE = r"제\s?(\d{1,4})\s?조(?:\s?의\s?(\d{1,3}))?"
_DETAIL = r"((?:\s?제\s?\d{1,3}\s?(?:항|호))*(?:\s?[가-하]목)?)"
_REF = re.compile(rf"{_ARTICLE}{_DETAIL}")
_APPENDIX = re.compile(r"\[?별표\s?(\d{1,3})(?:\s?의\s?(\d{1,2}))?\]?")
_HEADING = re.compile(rf"^\s*{_ARTICLE}\s*\(")
# what precedes a reference and names its law, read right-to-left from the reference
_BRACKETED = re.compile(r"「([^」]{1,80})」\s?$")
_FAMILY = re.compile(r"(?:^|[^가-힣A-Za-z0-9])(같은\s?법|같은\s?영|같은\s?규칙|이\s?법|이\s?영|이\s?규칙|법|영|규칙|시행령|시행규칙)\s?$")
_WORD_LAW = re.compile(r"(?:^|[^가-힣A-Za-z0-9])([가-힣A-Za-z0-9ㆍ·]{2,40}(?:법|법률|시행령|시행규칙|령|규칙))\s?$")
# what may sit between two items of one list ("제11조, 제14조 및 제16조", "제5조부터 제8조까지")
_LIST_GAP = re.compile(r"^\s*(?:,|ㆍ|·|및|또는|와|과|이나|나)?\s*(?:,|및|또는)?\s*$")
_RANGE_GAP = re.compile(r"^\s*(?:까지)?\s*(?:부터|에서|내지|~)\s*$")


@dataclass(frozen=True)
class LawRef:
    law_name: str
    article_key: str          # "80", "61-2", or "별표1"
    detail: str = ""          # "제1항제1호"
    raw: str = ""
    start: int = 0
    end: int = 0

    @property
    def key(self) -> str:
        return f"{self.law_name}:{self.article_key}"


def family_root(law_name: str) -> str:
    """'건축법 시행령' -> '건축법'."""
    for suffix in FAMILY_SUFFIXES:
        if law_name.endswith(suffix):
            return law_name[: -len(suffix)]
    return law_name


def _norm(name: str) -> str:
    return " ".join(name.split())


def _key(main: str, branch: str | None) -> str:
    return str(int(main)) + (f"-{int(branch)}" if branch else "")


def _family(word: str, law_name: str, last_named: str | None) -> str:
    p = word.replace(" ", "")
    root = family_root(law_name)
    if p in {"이법", "이영", "이규칙"}:
        return law_name
    if p == "같은법":
        return last_named or root
    if p == "같은영":
        return last_named or f"{root} 시행령"
    if p == "같은규칙":
        return last_named or f"{root} 시행규칙"
    if p == "법":
        return root
    if p in {"영", "시행령"}:
        return f"{root} 시행령"
    return f"{root} 시행규칙"


def _named_before(before: str, law_name: str, last_named: str | None, known: list[str]) -> tuple[str | None, bool]:
    """(law named right before a reference, whether it was an explicit full name)."""
    tail = before[-120:]
    m = _BRACKETED.search(tail)
    if m:
        return _norm(m.group(1)), True
    flat = _norm(tail)
    for name in known:  # longest first: unbracketed full names such as "국토의 계획 및 이용에 관한 법률"
        if flat.endswith(name) and (len(flat) == len(name) or not flat[-len(name) - 1].isalnum()):
            return name, True
    m = _FAMILY.search(tail)
    if m:
        return _family(m.group(1), law_name, last_named), False
    m = _WORD_LAW.search(tail)
    if m:
        return _norm(m.group(1)), True
    return None, False


def extract_refs(text: str, law_name: str, *, self_key: str | None = None,
                 known_laws: tuple[str, ...] | list[str] = ()) -> list[LawRef]:
    """References made by ``text`` (an article of ``law_name``), in order, without duplicates.

    ``known_laws`` lets unbracketed multi-word names ("국토의 계획 및 이용에 관한 법률 제77조")
    resolve; bracketed names, family words and one-word names ("주차장법") need no list.
    """
    text = text or ""
    heading = _HEADING.match(text)
    skip_until = heading.end() if heading else 0
    known = sorted({_norm(n) for n in known_laws if n}, key=len, reverse=True)
    out: list[LawRef] = []
    seen: set[str] = set()
    last_named: str | None = None
    prev_end, prev_law, prev_key = -1, None, None

    def add(ref: LawRef) -> None:
        if ref.key in seen or (self_key and ref.key == f"{law_name}:{self_key}"):
            return
        seen.add(ref.key)
        out.append(ref)

    matches = sorted(
        [(m.start(), "article", m) for m in _REF.finditer(text)]
        + [(m.start(), "appendix", m) for m in _APPENDIX.finditer(text)],
        key=lambda item: item[0],
    )
    for start, kind, m in matches:
        if start < skip_until:
            continue
        gap = text[prev_end:start] if prev_end >= 0 else None
        # a list inherits the law of its first item; a bare 별표 is always this law's own appendix
        in_list = kind == "article" and gap is not None and bool(_LIST_GAP.match(gap) or _RANGE_GAP.match(gap))
        named, explicit = (None, False) if in_list else _named_before(text[:start], law_name, last_named, known)
        if explicit:
            last_named = named
        if named is None:
            named = prev_law if in_list and prev_law else law_name
        if kind == "appendix":
            key = f"별표{int(m.group(1))}" + (f"-{int(m.group(2))}" if m.group(2) else "")
            add(LawRef(named, key, "", m.group(0).strip(), m.start(), m.end()))
            prev_end, prev_law, prev_key = m.end(), named, None
            continue
        key = _key(m.group(1), m.group(2))
        if gap is not None and _RANGE_GAP.match(gap) and prev_key and prev_law == named and "-" not in key + prev_key:
            lo, hi = int(prev_key), int(key)
            if 0 < hi - lo <= MAX_RANGE:
                for number in range(lo + 1, hi):
                    add(LawRef(named, str(number), "", "(range)", m.start(), m.end()))
        add(LawRef(named, key, re.sub(r"\s", "", m.group(3) or ""), m.group(0).strip(), m.start(), m.end()))
        prev_end, prev_law, prev_key = m.end(), named, key
    return out


def ref_keys(text: str, law_name: str, *, self_key: str | None = None,
             known_laws: tuple[str, ...] | list[str] = ()) -> list[str]:
    return [ref.key for ref in extract_refs(text, law_name, self_key=self_key, known_laws=known_laws)]
