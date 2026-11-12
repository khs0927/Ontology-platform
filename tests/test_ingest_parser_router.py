"""Format router (sion_ingestion.parsers): HWPX, scanned-PDF OCR, images, Docling preference."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx
import pytest
from sion_core.optional import is_available
from sion_ingestion import document_ingest, parsers
from sion_ingestion.parsers import DocumentUnreadable, ExtractedText, OcrConfig

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _p(text: str) -> str:
    return f'<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'


def _cell(text: str) -> str:
    return f"<hp:tc><hp:subList>{_p(text)}</hp:subList></hp:tc>"


def minimal_hwpx(path: Path) -> Path:
    table = (
        '<hp:p><hp:run><hp:tbl>'
        f'<hp:tr>{_cell("구분")}{_cell("기준")}</hp:tr>'
        f'<hp:tr>{_cell("복도 폭")}{_cell("1.2m 이상")}</hp:tr>'
        '</hp:tbl></hp:run></hp:p>'
    )
    section0 = f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{_p("제34조(직통계단의 설치)")}{_p("거실의 각 부분으로부터 계단까지 30미터 이하")}{table}</hs:sec>'
    section1 = f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{_p("부칙")}</hs:sec>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section1.xml", section1)
        archive.writestr("Contents/section0.xml", section0)
    return path


def blank_pdf(page_count: int) -> bytes:
    """A PDF with empty pages (no text layer), like a scan with the images stripped."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + i} 0 R" for i in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>")
    objects += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"] * page_count
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for name in ("SION_OCR_BASE_URL", "SION_OCR_MODEL", "SION_OCR_API_KEY", "SION_PARSER_PREFER"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- HWPX


EXPECTED_HWPX = (
    "제34조(직통계단의 설치)\n거실의 각 부분으로부터 계단까지 30미터 이하\n\n"
    "| 구분 | 기준 |\n| --- | --- |\n| 복도 폭 | 1.2m 이상 |\n\n부칙"
)


def test_builtin_hwpx_reader_keeps_section_order_and_tables(tmp_path):
    content = parsers.read_hwpx_builtin(minimal_hwpx(tmp_path / "law.hwpx"))
    assert content.extractor == "hwpx-builtin" and content.page_count == 2
    assert content.text == EXPECTED_HWPX


def test_router_uses_builtin_hwpx_without_the_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "is_available", lambda m: False if m == "hwp_hwpx_parser" else is_available(m))
    content = document_ingest.extract_text(minimal_hwpx(tmp_path / "law.hwpx"))
    assert content.extractor == "hwpx-builtin"


@pytest.mark.skipif(not is_available("hwp_hwpx_parser"), reason="hwp extra not installed")
def test_hwp_parser_reads_the_same_hwpx(tmp_path):
    content = document_ingest.extract_text(minimal_hwpx(tmp_path / "law.hwpx"))
    assert content.extractor == "hwp-hwpx-parser"
    for fragment in ("제34조(직통계단의 설치)", "30미터 이하", "복도 폭", "1.2m 이상", "부칙"):
        assert fragment in content.text


def test_broken_hwpx_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "is_available", lambda m: False if m == "hwp_hwpx_parser" else is_available(m))
    bad = tmp_path / "bad.hwpx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(DocumentUnreadable, match="HWPX"):
        document_ingest.extract_text(bad)
    empty = tmp_path / "empty.hwpx"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
    with pytest.raises(DocumentUnreadable, match="section"):
        parsers.read_hwpx_builtin(empty)


def test_oversized_xml_member_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "MAX_XML_MEMBER_BYTES", 10)
    with pytest.raises(DocumentUnreadable, match="larger than"):
        parsers.read_hwpx_builtin(minimal_hwpx(tmp_path / "law.hwpx"))


def test_hwp_without_extra_names_it(tmp_path, monkeypatch):
    import sion_core.optional as optional

    path = tmp_path / "law.hwp"
    path.write_bytes(b"\xd0\xcf\x11\xe0")
    real_import = optional.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "hwp_hwpx_parser":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(optional.importlib, "import_module", fake_import)
    with pytest.raises(ImportError, match="hwp"):
        document_ingest.extract_text(path)


# --------------------------------------------------------------------------- OCR

needs_pypdf = pytest.mark.skipif(not is_available("pypdf"), reason="documents extra not installed")
OCR = OcrConfig(base_url="http://ocr.test/v1", model="paddleocr-vl", api_key="k")


def _ocr_transport(seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        page = len(seen)
        return httpx.Response(200, json={"choices": [{"message": {"content": f"# 제{page}조\n본문 {page}"}}]})

    return httpx.MockTransport(handler)


@needs_pypdf
def test_scanned_pdf_goes_to_vision_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(blank_pdf(2))
    seen: list[dict] = []
    content = parsers.route(path, ocr=OCR, ocr_render=lambda p, n: [b"png-1", b"png-2"][:n],
                            ocr_transport=_ocr_transport(seen))
    assert content.extractor == "ocr:paddleocr-vl" and content.page_count == 2
    assert content.text == "<!-- page 1 -->\n# 제1조\n본문 1\n\n<!-- page 2 -->\n# 제2조\n본문 2"
    assert seen[0]["url"] == "http://ocr.test/v1/chat/completions" and seen[0]["auth"] == "Bearer k"
    parts = seen[0]["body"]["messages"][0]["content"]
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert seen[0]["body"]["model"] == "paddleocr-vl" and seen[0]["body"]["temperature"] == 0


@needs_pypdf
def test_scanned_pdf_without_ocr_is_skipped_with_a_hint(tmp_path):
    from sion_api.db import Base, build_engine, build_session_factory

    path = tmp_path / "scan.pdf"
    path.write_bytes(blank_pdf(1))
    content = parsers.route(path)
    assert content.extractor == "pypdf" and "SION_OCR_BASE_URL" in content.notes[0]
    engine = build_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(engine)
    with build_session_factory(engine)() as session:
        result = document_ingest.ingest_documents(session, [path])
    assert result["files"] == [] and "SION_OCR_BASE_URL" in result["skipped"][0]["reason"]


def test_image_needs_ocr_config(tmp_path):
    path = tmp_path / "page.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(DocumentUnreadable, match="SION_OCR_BASE_URL"):
        parsers.route(path)
    seen: list[dict] = []
    content = parsers.route(path, ocr=OCR, ocr_transport=_ocr_transport(seen))
    assert content.text.endswith("본문 1")
    assert seen[0]["body"]["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_ocr_endpoint_error_is_unreadable(tmp_path):
    path = tmp_path / "page.png"
    path.write_bytes(b"\x89PNG")
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "busy"}))
    with pytest.raises(DocumentUnreadable, match="OCR endpoint failed"):
        parsers.route(path, ocr=OCR, ocr_transport=transport)


def test_ocr_config_from_env(monkeypatch):
    assert OcrConfig.from_env() is None
    monkeypatch.setenv("SION_OCR_BASE_URL", "http://localhost:8000/v1/")
    monkeypatch.setenv("SION_OCR_MODEL", "PaddlePaddle/PaddleOCR-VL")
    monkeypatch.setenv("SION_OCR_MAX_PAGES", "5")
    config = OcrConfig.from_env()
    assert config.base_url == "http://localhost:8000/v1" and config.max_pages == 5 and config.api_key is None
    assert parsers.IMAGE_SUFFIXES <= parsers.supported_suffixes()


# --------------------------------------------------------------------------- Docling


def test_docling_preference_and_docling_only_types(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_docling(path: Path) -> ExtractedText:
        calls.append(path.suffix)
        return ExtractedText("# from docling", "docling", 1)

    monkeypatch.setattr(parsers, "read_docling", fake_docling)
    slides = tmp_path / "deck.pptx"
    slides.write_bytes(b"pk")
    assert parsers.route(slides).extractor == "docling"

    docx = tmp_path / "a.docx"
    docx.write_bytes(b"pk")
    sentinel = ExtractedText("from docx reader", "docx-builtin")
    assert parsers.route(docx, docx_reader=lambda p: sentinel) is sentinel  # docling not preferred

    monkeypatch.setenv("SION_PARSER_PREFER", "docling")
    monkeypatch.setattr(parsers, "is_available", lambda m: True if m == "docling" else is_available(m))
    assert parsers.route(docx, docx_reader=lambda p: sentinel).extractor == "docling"
    assert calls == [".pptx", ".docx"]


def test_docling_missing_names_the_install(tmp_path, monkeypatch):
    import sion_core.optional as optional

    real_import = optional.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name.startswith("docling"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(optional.importlib, "import_module", fake_import)
    path = tmp_path / "sheet.xlsx"
    path.write_bytes(b"pk")
    with pytest.raises(ImportError, match="docling"):
        parsers.route(path)
