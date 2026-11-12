"""Format router for document parsing: the right parser per file type, with fallbacks.

One parser does not fit Korean regulation work: Office files and born-digital PDFs read best with a
layout-aware parser, HWP/HWPX needs a native reader, and scanned pages need a vision OCR model.
:func:`route` picks, per suffix, the first backend that is installed and configured:

==========  ==================================================================================
Suffix      Backends, in order
==========  ==================================================================================
``.hwpx``   kordoc → ``hwp-hwpx-parser`` (``hwp`` extra) → built-in HWPX XML reader
``.hwp``    kordoc → ``hwp-hwpx-parser`` (``hwp`` extra)
``.pdf``    preferred parser (``SION_PARSER_PREFER=kordoc|docling``) → pypdf (``documents`` extra);
            no text layer → vision OCR (``SION_OCR_BASE_URL`` + ``SION_OCR_MODEL``) → kordoc OCR
``.docx``   preferred parser → python-docx → built-in OOXML reader
``.pptx``,
``.xlsx``   preferred parser → Docling → kordoc
``.xls``    kordoc
``.html``   Docling
images      vision OCR → kordoc OCR
==========  ==================================================================================

kordoc (MIT, Node 20+, ``npm install -g kordoc``) is the Korean public-document parser: HWP 3/5,
HWPX, statute appendix (별표) tables, PDF with local OCR. It is found on ``PATH`` or through
``SION_KORDOC_BIN`` and run as a subprocess (``SION_KORDOC=off`` disables it).
Docling is not an extra (it pulls in torch); ``pip install docling`` enables it. Vision OCR talks
to any OpenAI-compatible chat endpoint that accepts images, such as PaddleOCR-VL or Qwen-VL served
by vLLM; ``pypdfium2`` (``ocr`` extra) renders PDF pages for it. Every result names the backend
that produced it, so evidence rows record how a text was obtained.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from sion_core import MissingExtra, require
from sion_core.optional import is_available

TEXT_SUFFIXES = frozenset({".md", ".txt", ".csv"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"})
DOCLING_ONLY_SUFFIXES = frozenset({".pptx", ".xlsx", ".html", ".htm"})
KORDOC_SUFFIXES = frozenset({".hwp", ".hwpx", ".pdf", ".docx", ".xlsx", ".xls", ".pptx"}) | IMAGE_SUFFIXES
DOCUMENT_SUFFIXES = (TEXT_SUFFIXES | {".docx", ".pdf", ".hwpx", ".hwp", ".xls"} | DOCLING_ONLY_SUFFIXES
                     | IMAGE_SUFFIXES)

# A PDF page with fewer extractable characters than this is treated as scanned.
MIN_TEXT_CHARS_PER_PAGE = 20
OCR_PROMPT = (
    "Transcribe this document page to Markdown. Keep the reading order, headings, article numbers "
    "and every table as a Markdown table. Output only the page content."
)


class DocumentUnreadable(ValueError):
    """The file has a supported suffix but its content cannot be read."""


@dataclass(frozen=True)
class ExtractedText:
    text: str
    extractor: str
    page_count: int | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------- configuration


@dataclass(frozen=True)
class OcrConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 120.0
    max_pages: int = 50

    @classmethod
    def from_env(cls) -> OcrConfig | None:
        base_url, model = os.getenv("SION_OCR_BASE_URL"), os.getenv("SION_OCR_MODEL")
        if not base_url or not model:
            return None
        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=os.getenv("SION_OCR_API_KEY") or None,
            timeout=float(os.getenv("SION_OCR_TIMEOUT_SECONDS", "120")),
            max_pages=int(os.getenv("SION_OCR_MAX_PAGES", "50")),
        )


def kordoc_bin() -> str | None:
    """Path of the kordoc CLI, or None when it is not installed or disabled (``SION_KORDOC=off``)."""
    if os.getenv("SION_KORDOC", "").strip().lower() in {"off", "0", "false", "no"}:
        return None
    configured = os.getenv("SION_KORDOC_BIN")
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("kordoc")


def preferred() -> str | None:
    """``SION_PARSER_PREFER`` when that parser is actually available: 'kordoc', 'docling' or None."""
    choice = os.getenv("SION_PARSER_PREFER", "").strip().lower()
    if choice == "docling" and is_available("docling"):
        return "docling"
    if choice == "kordoc" and kordoc_bin():
        return "kordoc"
    return None


def prefer_docling() -> bool:
    return preferred() == "docling"


def supported_suffixes() -> set[str]:
    """Suffixes ingestible with the libraries and endpoints configured right now."""
    suffixes = set(TEXT_SUFFIXES) | {".docx", ".hwpx"}  # built-in readers
    if kordoc_bin():
        suffixes |= KORDOC_SUFFIXES
    if is_available("pypdf") or is_available("docling"):
        suffixes.add(".pdf")
    if is_available("hwp_hwpx_parser"):
        suffixes.add(".hwp")
    if is_available("docling"):
        suffixes |= DOCLING_ONLY_SUFFIXES
    if OcrConfig.from_env() is not None:
        suffixes |= IMAGE_SUFFIXES
    return suffixes


# ---------------------------------------------------------------- HWP / HWPX

_SECTION = re.compile(r"^Contents/section(\d+)\.xml$")
# An HWPX section is rarely over a few MB; refuse decompression bombs before reading.
MAX_XML_MEMBER_BYTES = 64 * 1024 * 1024


def parse_xml(data: bytes) -> ElementTree.Element:
    """Parse untrusted XML: defusedxml when installed (rejects entity expansion), else stdlib.

    The stdlib parser on Python 3.12+ ships expat >= 2.6, which never resolves external entities and
    caps entity amplification, so the fallback is safe for the bounded members read here.
    """
    if is_available("defusedxml"):
        from defusedxml import ElementTree as safe_tree

        return safe_tree.fromstring(data)
    return ElementTree.fromstring(data)  # noqa: S314 - see docstring


def read_zip_member(archive: zipfile.ZipFile, name: str) -> bytes:
    if archive.getinfo(name).file_size > MAX_XML_MEMBER_BYTES:
        raise DocumentUnreadable(f"{name} is larger than {MAX_XML_MEMBER_BYTES} bytes uncompressed")
    return archive.read(name)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hwpx_paragraph_text(p: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        name = _local(node.tag)
        if name == "tbl":  # nested tables are rendered separately
            break
        if name == "t":
            parts.append("".join(node.itertext()))
        elif name == "tab":
            parts.append("\t")
        elif name == "lineBreak":
            parts.append("\n")
    return "".join(parts).strip()


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _hwpx_table(tbl: ElementTree.Element) -> list[str]:
    rows: list[list[str]] = []
    for tr in (n for n in tbl if _local(n.tag) == "tr"):
        cells = []
        for tc in (n for n in tr if _local(n.tag) == "tc"):
            texts = [_hwpx_paragraph_text(p) for p in tc.iter() if _local(p.tag) == "p"]
            cells.append(_cell(" ".join(t for t in texts if t)))
        rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines


def _hwpx_block(element: ElementTree.Element, lines: list[str]) -> None:
    for child in element:
        name = _local(child.tag)
        if name == "p":
            tables = [n for n in child.iter() if _local(n.tag) == "tbl"]
            text = _hwpx_paragraph_text(child)
            if text:
                lines.append(text)
            for tbl in tables:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.extend(_hwpx_table(tbl))
                lines.append("")
        elif name == "tbl":
            lines.extend(_hwpx_table(child))
            lines.append("")
        else:
            _hwpx_block(child, lines)


def read_hwpx_builtin(path: Path) -> ExtractedText:
    """Body text and tables (as Markdown) of an HWPX file (OWPML: a ZIP of XML sections)."""
    try:
        with zipfile.ZipFile(path) as archive:
            sections = sorted(
                (n for n in archive.namelist() if _SECTION.match(n)), key=lambda n: int(_SECTION.match(n).group(1))
            )
            if not sections:
                raise DocumentUnreadable("HWPX has no Contents/section*.xml")
            lines: list[str] = []
            for name in sections:
                _hwpx_block(parse_xml(read_zip_member(archive, name)), lines)
    except DocumentUnreadable:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError) as exc:
        raise DocumentUnreadable(f"HWPX could not be read ({type(exc).__name__}: {exc})") from exc
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return ExtractedText(text, "hwpx-builtin", len(sections))


def read_hwp_parser(path: Path) -> ExtractedText:
    """HWP 5.0 or HWPX through hwp-hwpx-parser (Apache-2.0, pure Python); tables inline as Markdown."""
    module = require("hwp_hwpx_parser", extra="hwp")
    options = module.ExtractOptions(
        table_style=module.TableStyle.MARKDOWN, image_marker=module.ImageMarkerStyle.NONE
    )
    try:
        with module.Reader(str(path)) as reader:
            if reader.is_encrypted:
                raise DocumentUnreadable("encrypted HWP")
            text = reader.extract_text(options) or ""
    except DocumentUnreadable:
        raise
    except Exception as exc:  # the library raises several error types for damaged files
        raise DocumentUnreadable(f"HWP could not be read ({type(exc).__name__}: {exc})") from exc
    return ExtractedText(re.sub(r"\n{3,}", "\n\n", text).strip(), "hwp-hwpx-parser")


# ---------------------------------------------------------------- kordoc


def read_kordoc(path: Path, *, ocr: bool = False, binary: str | None = None) -> ExtractedText:
    """Markdown from the kordoc CLI (``--format json``). ``ocr`` turns on its built-in OCR."""
    binary = binary or kordoc_bin()
    if not binary:
        raise DocumentUnreadable("kordoc is not installed: npm install -g kordoc (Node 20+) or set SION_KORDOC_BIN")
    args = [binary, str(path.resolve()), "--format", "json", "--no-images"]
    if ocr:
        args.append("--ocr")
    timeout = float(os.getenv("SION_KORDOC_TIMEOUT_SECONDS", "300"))
    try:
        done = subprocess.run(args, capture_output=True, timeout=timeout, check=False)  # noqa: S603 - fixed argv
    except subprocess.TimeoutExpired as exc:
        raise DocumentUnreadable(f"kordoc timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise DocumentUnreadable(f"kordoc could not start ({exc})") from exc
    try:
        result = json.loads(done.stdout.decode("utf-8"))
    except ValueError as exc:
        stderr = done.stderr.decode("utf-8", "replace").strip()[-300:]
        raise DocumentUnreadable(f"kordoc returned no JSON (exit {done.returncode}: {stderr})") from exc
    if not isinstance(result, dict) or not result.get("success"):
        error = result.get("error") if isinstance(result, dict) else None
        raise DocumentUnreadable(f"kordoc could not read the file ({error or 'unknown error'})")
    notes = tuple(str(w.get("message")) for w in result.get("warnings") or [] if isinstance(w, dict) and w.get("message"))
    pages = result.get("pageCount") or (result.get("metadata") or {}).get("pageCount")
    return ExtractedText((result.get("markdown") or "").strip(), "kordoc" + ("+ocr" if ocr else ""),
                         int(pages) if pages else None, notes)


# ---------------------------------------------------------------- Docling


def read_docling(path: Path) -> ExtractedText:
    """Layout-aware Markdown (headings, reading order, tables) through Docling (MIT)."""
    try:
        converter_module = importlib.import_module("docling.document_converter")
    except ImportError as exc:  # not an extra: Docling pulls in torch, so it is a deliberate install
        missing = MissingExtra("docling", None)
        missing.args = (f"{missing.args[0]} Install it with: pip install docling (see docs/INGESTION.md)",)
        raise missing from exc
    try:
        result = converter_module.DocumentConverter().convert(str(path))
        document = result.document
        text = document.export_to_markdown()
        pages = getattr(document, "pages", None)
    except Exception as exc:
        raise DocumentUnreadable(f"Docling could not read the file ({type(exc).__name__}: {exc})") from exc
    return ExtractedText(text, "docling", len(pages) if pages else None)


# ---------------------------------------------------------------- vision OCR

Render = Callable[[Path, int], list[bytes]]


def render_pdf_pages(path: Path, max_pages: int) -> list[bytes]:
    """PNG bytes per page (pypdfium2, ``ocr`` extra), at about 144 dpi."""
    import io

    pdfium = require("pypdfium2", extra="ocr")
    pdf = pdfium.PdfDocument(str(path))
    try:
        out = []
        for index in range(min(len(pdf), max_pages)):
            image = pdf[index].render(scale=2).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            out.append(buffer.getvalue())
        return out
    finally:
        pdf.close()


def _mime(path: Path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".tif": "image/tiff",
            ".tiff": "image/tiff"}.get(path.suffix.lower(), "image/png")


def ocr_images(images: list[tuple[bytes, str]], config: OcrConfig, *, transport=None) -> list[str]:
    """One Markdown string per image from an OpenAI-compatible vision chat endpoint."""
    import httpx

    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    pages: list[str] = []
    with httpx.Client(timeout=config.timeout, transport=transport, headers=headers) as client:
        for data, mime in images:
            url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
            payload = {
                "model": config.model,
                "temperature": 0,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                    {"type": "text", "text": OCR_PROMPT},
                ]}],
            }
            try:
                response = client.post(f"{config.base_url}/chat/completions", json=payload)
                response.raise_for_status()
                pages.append((response.json()["choices"][0]["message"]["content"] or "").strip())
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                raise DocumentUnreadable(f"OCR endpoint failed ({type(exc).__name__}: {exc})") from exc
    return pages


def read_ocr(path: Path, config: OcrConfig, *, render: Render = render_pdf_pages, transport=None) -> ExtractedText:
    if path.suffix.lower() == ".pdf":
        images = [(png, "image/png") for png in render(path, config.max_pages)]
    else:
        images = [(path.read_bytes(), _mime(path))]
    pages = ocr_images(images, config, transport=transport)
    text = "\n\n".join(f"<!-- page {i} -->\n{p}" for i, p in enumerate(pages, 1) if p)
    return ExtractedText(text, f"ocr:{config.model}", len(pages))


# ---------------------------------------------------------------- PDF / DOCX


def read_pdf_pypdf(path: Path) -> tuple[ExtractedText, list[str]]:
    pypdf = require("pypdf", extra="documents")
    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted:
            raise DocumentUnreadable("encrypted PDF")
        pages = [page.extract_text() or "" for page in reader.pages]
    except DocumentUnreadable:
        raise
    except Exception as exc:  # pypdf raises several error types for damaged files
        raise DocumentUnreadable(f"PDF could not be read ({type(exc).__name__}: {exc})") from exc
    return ExtractedText("\n".join(pages), "pypdf", len(pages)), pages


def is_scanned(pages: list[str]) -> bool:
    return bool(pages) and all(len(p.strip()) < MIN_TEXT_CHARS_PER_PAGE for p in pages)


# ---------------------------------------------------------------- router


def route(path: Path, *, docx_reader: Callable[[Path], ExtractedText] | None = None,
          ocr: OcrConfig | None = None, ocr_render: Render = render_pdf_pages, ocr_transport=None) -> ExtractedText:
    """Parse one file with the best available backend. Raises :class:`MissingExtra` or :class:`DocumentUnreadable`."""
    suffix = path.suffix.lower()
    ocr = ocr if ocr is not None else OcrConfig.from_env()
    kordoc = kordoc_bin()
    choice = preferred()

    if suffix in TEXT_SUFFIXES:
        return ExtractedText(path.read_text(encoding="utf-8", errors="replace"), "text")

    if suffix in {".hwp", ".hwpx"}:
        if kordoc:
            return read_kordoc(path, binary=kordoc)
        if suffix == ".hwpx" and not is_available("hwp_hwpx_parser"):
            return read_hwpx_builtin(path)
        return read_hwp_parser(path)

    if choice == "kordoc" and suffix in KORDOC_SUFFIXES - IMAGE_SUFFIXES:
        return read_kordoc(path, binary=kordoc, ocr=suffix == ".pdf" and ocr is None)
    if choice == "docling" and suffix in {".pdf", ".docx"} | DOCLING_ONLY_SUFFIXES:
        return read_docling(path)

    if suffix == ".pdf":
        if not is_available("pypdf") and is_available("docling"):
            return read_docling(path)
        if not is_available("pypdf") and kordoc:
            return read_kordoc(path, binary=kordoc, ocr=ocr is None)
        extracted, pages = read_pdf_pypdf(path)
        if not is_scanned(pages):
            return extracted
        if ocr is not None:
            return read_ocr(path, ocr, render=ocr_render, transport=ocr_transport)
        if kordoc:
            return read_kordoc(path, binary=kordoc, ocr=True)
        return ExtractedText(extracted.text, extracted.extractor, extracted.page_count, (
            "no text layer; set SION_OCR_BASE_URL and SION_OCR_MODEL, "
            "or install kordoc, to OCR scans",))

    if suffix == ".docx":
        if docx_reader is None:
            raise DocumentUnreadable("no DOCX reader")
        return docx_reader(path)

    if suffix in DOCLING_ONLY_SUFFIXES:
        if not is_available("docling") and kordoc and suffix in KORDOC_SUFFIXES:
            return read_kordoc(path, binary=kordoc)
        return read_docling(path)

    if suffix == ".xls":
        return read_kordoc(path, binary=kordoc)

    if suffix in IMAGE_SUFFIXES:
        if ocr is not None:
            return read_ocr(path, ocr, transport=ocr_transport)
        if kordoc:
            return read_kordoc(path, binary=kordoc, ocr=True)
        raise DocumentUnreadable("image files need OCR: set SION_OCR_BASE_URL and SION_OCR_MODEL, or install kordoc")

    raise DocumentUnreadable(f"unsupported document type: {suffix or '(none)'}")
