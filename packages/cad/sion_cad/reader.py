"""The one DXF reading path for the monorepo.

Every DXF consumer goes through this module:

* ``sion_cad.dxf``            Sion ingestion (claims + evidence)
* ``god_cad.adapters.dxf``    GOD-CAD evidence-linked geometry analysis (packages/cad/god-cad)
* ``aec_intelligence.dxf``    AEC/CAIR normalisation (packages/aec)

``ezdxf`` (extra ``cad``) is authoritative. :func:`open_dxf` adds the robustness
that previously lived only in ``aec_intelligence``: strict read, then
``ezdxf.recover`` for damaged/legacy files, and CP949 detection for Korean
drawings whose header claims a Western code page. Recovery fixes are returned
as warnings so they stay auditable.

Without ezdxf, :func:`read_entities` falls back to a small built-in text
parser (TEXT/MTEXT, INSERT, LINE, LWPOLYLINE in the ENTITIES section).

:func:`dxf_census` produces the All-In-Cad ``DxfEvidence`` shape (model-space
handle/type/layer census) so the Sion lane and the All-In-Cad headless lane can
be cross-checked (``docs/INTEGRATION_CONTRACTS.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HANGUL_RE = re.compile("[\uac00-\ud7a3]")


class DxfReaderUnavailable(RuntimeError):
    """ezdxf is needed for this operation (``pip install 'sion-ontology-platform[cad]'``)."""


def _ezdxf():
    try:
        import ezdxf
    except ImportError:
        return None
    return ezdxf


def ezdxf_available() -> bool:
    return _ezdxf() is not None


def sniff_korean_encoding(path: str | Path, encoding: str) -> str | None:
    """Detect CP949 bytes in a legacy DXF whose header claims a Western code page."""
    if encoding.lower().replace("-", "") not in {"cp1252", "windows1252", "latin1", "iso88591", "ascii"}:
        return None
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if not any(byte >= 0x80 for byte in data):
        return None
    try:
        decoded = data.decode("cp949")
    except UnicodeDecodeError:
        return None
    non_ascii = sum(1 for ch in decoded if ord(ch) >= 0x80)
    hangul = len(_HANGUL_RE.findall(decoded))
    return "cp949" if hangul >= 2 and hangul >= 0.6 * non_ascii else None


def decode_dxf_text(value: Any) -> str:
    """Decode ``\\U+AC70``-style escapes that legacy DXF writers use outside the code page."""
    text = str(value)
    if "\\U+" in text or "\\u+" in text:
        try:
            from ezdxf.lldxf.encoding import decode_dxf_unicode

            return decode_dxf_unicode(text)
        except Exception:
            return re.sub(r"\\[Uu]\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), text)
    return text


def open_dxf(path: str | Path) -> tuple[Any, list[str]]:
    """Read a DXF with ezdxf: strict, then ``ezdxf.recover``; re-read CP949 when detected.

    Returns ``(document, warnings)``. Raises :class:`DxfReaderUnavailable` without ezdxf and
    ``IOError`` for unreadable files.
    """
    ezdxf = _ezdxf()
    if ezdxf is None:
        raise DxfReaderUnavailable("ezdxf is required for DXF ingestion; install the [cad] extra")
    warnings: list[str] = []
    try:
        doc = ezdxf.readfile(str(path))
    except IOError:
        raise
    except Exception as exc:
        from ezdxf import recover

        warnings.append(f"DXF strict read failed ({type(exc).__name__}: {exc}); recovered with ezdxf.recover")
        doc, auditor = recover.readfile(str(path))
        warnings.extend(f"recover fix: {fix.message}" for fix in list(auditor.fixes)[:50])
        warnings.extend(f"recover error: {error.message}" for error in list(auditor.errors)[:50])
    codepage = str(doc.header.get("$DWGCODEPAGE", "") or "")
    if doc.dxfversion < "AC1021":
        sniffed = sniff_korean_encoding(path, str(doc.encoding))
        if sniffed:
            warnings.append(f"$DWGCODEPAGE={codepage or 'missing'} but text bytes are {sniffed}; re-read as {sniffed}")
            doc = ezdxf.readfile(str(path), encoding=sniffed)
        elif codepage and codepage.upper() != "ANSI_1252":
            warnings.append(f"Legacy DXF decoded with $DWGCODEPAGE={codepage} ({doc.encoding})")
    return doc, warnings


# --------------------------------------------------------------------------- items


@dataclass
class DxfReadResult:
    items: list[dict[str, Any]]
    parser: str  # "ezdxf" | "text-fallback"
    warnings: list[str] = field(default_factory=list)


def _items_from_document(doc: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entity in doc.modelspace():
        kind = entity.dxftype()
        layer = entity.dxf.get("layer", "")
        handle = str(entity.dxf.get("handle", "") or "")
        if kind == "TEXT" and entity.dxf.get("text"):
            items.append({"kind": "annotation", "name": decode_dxf_text(entity.dxf.text), "layer": layer, "handle": handle})
        elif kind == "MTEXT" and entity.text:
            items.append({"kind": "annotation", "name": decode_dxf_text(entity.plain_text()), "layer": layer, "handle": handle})
        elif kind == "INSERT":
            items.append({"kind": "block", "name": entity.dxf.name, "layer": layer, "handle": handle})
        elif kind == "LINE":
            items.append({"kind": "segment", "name": f"line:{layer or '0'}", "layer": layer, "handle": handle})
        elif kind == "LWPOLYLINE":
            closed = bool(entity.closed)
            items.append({
                "kind": "space" if closed else "segment",
                "name": f"{'space' if closed else 'polyline'}:{layer or '0'}",
                "layer": layer,
                "handle": handle,
            })
    return items


def _decode_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        decoded = data.decode("cp949")
        if _HANGUL_RE.search(decoded):
            return decoded
    except UnicodeDecodeError:
        pass
    return data.decode("utf-8", errors="replace")


def _pairs(body: str) -> list[tuple[str, str]]:
    lines = [line.strip() for line in body.splitlines()]
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def _sections(text: str) -> list[tuple[str, str]]:
    """Group (code, value) pairs into entities, split on group code 0.

    Group codes are whitespace-padded in many writers (e.g. "  0"), so codes are
    compared after stripping. Only the ENTITIES section is scanned when present,
    so BLOCKS definitions are not double-counted.
    """
    lines = text.splitlines()
    pairs = [(lines[i].strip(), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]
    has_entities_section = any(code == "2" and value == "ENTITIES" for code, value in pairs)
    in_entities = not has_entities_section
    sections: list[tuple[str, str]] = []
    current: str | None = None
    body: list[str] = []
    previous_section = False
    for code, value in pairs:
        if code == "0":
            if current is not None and in_entities:
                sections.append((current, "\n".join(body)))
            current, body = None, []
            if value == "SECTION":
                previous_section = True
                continue
            if value == "ENDSEC":
                in_entities = in_entities and not has_entities_section
                continue
            if value != "EOF":
                current = value
            previous_section = False
            continue
        if previous_section and code == "2":
            in_entities = value == "ENTITIES"
            previous_section = False
            continue
        if current is not None:
            body.extend([code, value])
    if current is not None and in_entities:
        sections.append((current, "\n".join(body)))
    return sections


_MTEXT_PARAM_CODES = re.compile(r"\\[fFhHwWqQtTaAcCpP][^;\\{}]*;")
_MTEXT_STACK = re.compile(r"\\S([^;^/#]*)[\^/#]([^;]*);")
_MTEXT_TOGGLES = re.compile(r"\\[LlOoKkNn]")


def mtext_plain_text(raw: str) -> str:
    """Approximate ezdxf's ``MText.plain_text()`` for the built-in parser."""
    text = raw.replace("\\\\", "\x00")  # escaped backslash
    text = text.replace("\\{", "\x01").replace("\\}", "\x02")
    text = text.replace("\\P", "\n").replace("\\~", "\u00a0")
    text = _MTEXT_STACK.sub(lambda m: f"{m.group(1)}/{m.group(2)}", text)
    text = _MTEXT_PARAM_CODES.sub("", text)
    text = _MTEXT_TOGGLES.sub("", text)
    text = text.replace("{", "").replace("}", "")
    return text.replace("\x00", "\\").replace("\x01", "{").replace("\x02", "}")


def parse_text_items(path: str | Path) -> list[dict[str, Any]]:
    """Dependency-free fallback parser."""
    text = _decode_bytes(Path(path).read_bytes())
    items: list[dict[str, Any]] = []
    for kind, body in _sections(text):
        values = {code: value for code, value in _pairs(body)}
        layer = values.get("8", "")
        handle = values.get("5", "")
        if kind == "MTEXT" and values.get("1"):
            pairs = _pairs(body)
            raw = "".join(value for code, value in pairs if code == "3") + values["1"]
            items.append({"kind": "annotation", "name": decode_dxf_text(mtext_plain_text(raw)), "layer": layer, "handle": handle})
        elif kind == "TEXT" and values.get("1"):
            items.append({"kind": "annotation", "name": decode_dxf_text(values["1"]), "layer": layer, "handle": handle})
        elif kind == "INSERT" and values.get("2"):
            items.append({"kind": "block", "name": values["2"], "layer": layer, "handle": handle})
        elif kind == "LINE":
            items.append({"kind": "segment", "name": f"line:{values.get('8', '0')}", "layer": layer, "handle": handle})
        elif kind == "LWPOLYLINE":
            try:
                closed = bool(int(values.get("70", "0")) & 1)
            except ValueError:
                closed = False
            items.append({
                "kind": "space" if closed else "segment",
                "name": f"{'space' if closed else 'polyline'}:{values.get('8', '0')}",
                "layer": layer,
                "handle": handle,
            })
    return items


def read_entities(path: str | Path, *, prefer_ezdxf: bool = True) -> DxfReadResult:
    """Semantic items from model space: ezdxf when installed, else the built-in parser.

    If ezdxf is installed but cannot read the file even with ``recover``, the
    built-in parser is tried and the ezdxf failure is kept as a warning.
    """
    warnings: list[str] = []
    if prefer_ezdxf and ezdxf_available():
        try:
            doc, warnings = open_dxf(path)
            return DxfReadResult(_items_from_document(doc), "ezdxf", warnings)
        except IOError:
            raise
        except Exception as exc:
            warnings = [f"ezdxf failed ({type(exc).__name__}: {exc}); used built-in text parser"]
    return DxfReadResult(parse_text_items(path), "text-fallback", warnings)


# --------------------------------------------------------------------------- census

#: Entities that belong to a parent entity and are not model-space members.
_SUB_ENTITIES = frozenset({"VERTEX", "SEQEND", "ATTRIB"})


def _census_from_document(doc: Any) -> tuple[list[dict[str, Any]], bool, list[str]]:
    # Same audit ezdxf.recover runs (and All-In-Cad relies on). Fixes can remove entities,
    # e.g. a DIMENSION without its geometry block, so they are reported as warnings.
    auditor = doc.audit()
    fixes = [f"audit fix: {fix.message}" for fix in list(auditor.fixes)[:50]]
    entities = []
    for entity in doc.modelspace():
        handle = entity.dxf.get("handle", None)
        entities.append({
            "handle": str(handle) if handle is not None else None,
            "dxftype": entity.dxftype(),
            "layer": str(entity.dxf.get("layer", "0")),
        })
    return entities, bool(auditor.has_errors), fixes


def _census_from_text(path: str | Path) -> list[dict[str, Any]]:
    text = _decode_bytes(Path(path).read_bytes())
    entities = []
    for kind, body in _sections(text):
        if kind in _SUB_ENTITIES:
            continue
        values = {code: value for code, value in _pairs(body)}
        if values.get("67") == "1":  # paper space
            continue
        entities.append({"handle": values.get("5") or None, "dxftype": kind, "layer": values.get("8", "0")})
    return entities


def dxf_census(path: str | Path, *, prefer_ezdxf: bool = True) -> dict[str, Any]:
    """Model-space census in the All-In-Cad ``DxfEvidence`` shape (contract ``all-in-cad-dxf-evidence``).

    With ezdxf the document is opened via :func:`open_dxf` (so CP949 layer names decode) and
    audited like ``ezdxf.recover``. The built-in parser cannot audit, so it reports
    ``auditor_has_errors=None`` rather than claiming a clean file.
    """
    warnings: list[str] = []
    entities: list[dict[str, Any]] | None = None
    has_errors: bool | None = None
    parser = "text-fallback"
    if prefer_ezdxf and ezdxf_available():
        try:
            doc, warnings = open_dxf(path)
            entities, has_errors, fixes = _census_from_document(doc)
            warnings = [*warnings, *fixes]
            parser = "ezdxf"
        except IOError:
            raise
        except Exception as exc:
            warnings = [f"ezdxf failed ({type(exc).__name__}: {exc}); used built-in text parser"]
    if entities is None:
        entities = _census_from_text(path)
    layer_counts: dict[str, int] = {}
    for entity in entities:
        layer_counts[entity["layer"]] = layer_counts.get(entity["layer"], 0) + 1
    return {
        "path": str(path),
        "entity_count": len(entities),
        "layer_counts": dict(sorted(layer_counts.items())),
        "entities": entities,
        "auditor_has_errors": has_errors,
        "parser": parser,
        "warnings": warnings,
    }
