# Document parsing

`POST /api/v1/ingest/documents` and relation extraction read files through one format router,
`sion_ingestion.parsers.route`. It picks, per file type, the first backend that is installed and
configured, and every result records that backend in the document node's `extractor` property
(plus `parser_notes` when something was degraded), so evidence always says how a text was read.

| Type | Backends, in order | Install |
|---|---|---|
| `.md` `.txt` `.csv` | plain text | core |
| `.hwpx` | hwp-hwpx-parser → built-in OWPML reader (body text + tables as Markdown) | `hwp` extra, optional |
| `.hwp` (HWP 5.0) | hwp-hwpx-parser | `hwp` extra |
| `.pdf` | Docling (when preferred) → pypdf; a PDF with no text layer goes to vision OCR | `documents` extra; `ocr` extra + endpoint for scans |
| `.docx` | Docling (when preferred) → python-docx → built-in OOXML reader | `documents` extra, optional |
| `.pptx` `.xlsx` `.html` | Docling | `pip install docling` |
| `.png` `.jpg` `.webp` `.tif` | vision OCR | endpoint only |

A file whose backend is missing is listed under `skipped` with the reason (the extra to install or
the setting to set). It is never guessed.

## Vision OCR for scans and images

Korean regulation sources are often scanned 고시/공고 PDFs. The router sends each page to any
OpenAI-compatible `/chat/completions` endpoint that accepts images and asks for Markdown with
tables kept. The recommended model is **PaddleOCR-VL** (Apache-2.0, 0.9B, strong on Korean and on
tables); Qwen2.5/3-VL served the same way also works.

```bash
pip install -e '.[documents,ocr]'
# serve the model, for example with vLLM on a GPU host
vllm serve PaddlePaddle/PaddleOCR-VL --trust-remote-code --port 8118
export SION_OCR_BASE_URL=http://gpu-host:8118/v1
export SION_OCR_MODEL=PaddlePaddle/PaddleOCR-VL
# optional
export SION_OCR_API_KEY=...            # sent as a bearer token
export SION_OCR_TIMEOUT_SECONDS=120
export SION_OCR_MAX_PAGES=50           # pages rendered per PDF
```

A PDF counts as scanned when every page has fewer than 20 extractable characters. Without an
endpoint such a PDF is skipped with `no extractable text (no text layer); set SION_OCR_BASE_URL …`.
OCR output is model text: it stays `unverified` like every other extraction and goes through
`/review` before it becomes canonical.

## Docling

[Docling](https://github.com/docling-project/docling) (MIT) gives layout-aware Markdown with
reading order and table structure. It is not an extra because it pulls in torch; install it
deliberately with `pip install docling`. Once installed it handles PPTX/XLSX/HTML, and
`SION_PARSER_PREFER=docling` makes it the first choice for PDF and DOCX too.

## Not used, and why

- **pyhwp** — AGPL-3.0; hwp-hwpx-parser (Apache-2.0) covers HWP 5.0 and HWPX.
- **Firecrawl** — AGPL-3.0 server; use Crawl4AI (Apache-2.0) for web sources when crawling is added.
- **Cloud document APIs** — the platform is local-first; the OCR endpoint can be self-hosted.
