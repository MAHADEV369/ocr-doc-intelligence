# Production hybrid extractor

`src/production_extractor.py` is the runnable “best results” tool: it combines the
measured strengths of the engines instead of using one engine for everything.

## Routing

| Page type | Text | Tables |
|---|---|---|
| Digital page | PyMuPDF native text | PyMuPDF table finder |
| Digital statement page with weak/absent native tables | PyMuPDF native text | Docling (vector page, no OCR) |
| Ordinary scanned page | 300 DPI render → CLAHE/deskew → Tesseract first | only when the page looks like a statement |
| Low-confidence scan or table-heavy statement | escalate to PaddleOCR PP-OCRv6 | Docling TableFormer grid + OCR cell fusion |
| Blank page | no OCR | none |
| Known bad vendor OCR layer | forced re-OCR path | same as scanned |

Tesseract is the default scan path. PaddleOCR is loaded only when Tesseract's mean
word confidence is below the threshold, when the page produces no text, or when a
statement page has too few recognised items. This avoids paying a 7 GB / 44 s/page
cost on ordinary scans. Docling is only invoked on statement pages when native
tables are missing or numerically thin.

## Table fusion

For scanned pages:

1. Docling detects the table and returns cell bounding boxes.
2. The OCR engine returns text boxes and scores for the whole page.
3. Each Docling cell receives the OCR text whose box centre falls inside the cell.
4. Numbers are only replaced when the numeric values agree; non-numeric text is
   replaced only when string similarity and OCR confidence are high. A longer OCR
   string is not automatically preferred.
5. Column-sum and row-sum cross-foot checks run where a clear total exists.
6. The table status becomes `verified`, `arithmetic_ok` or `needs_review`.

No OCR text is used to overwrite a native text-layer value on a digital page.

## CLI

```bash
# one page
python -m src.production_extractor data/raw/hdfc/annual_report_fy2026.pdf \
  -o data/structured/production/hdfc_p472 --start-page 472 --max-pages 1

# a whole scanned document, Tesseract only
python -m src.production_extractor scan.pdf -o out/scan --force-ocr --dpi 300 --ocr-engine tesseract

# force PaddleOCR for a difficult scan
python -m src.production_extractor scan.pdf -o out/scan --force-ocr --ocr-engine paddle
```

Outputs:

```
out/
  result.json          page text, routes, tables, checks, timings
  result.partial.json  checkpoint every 10 pages
  document.md          human-readable text + Markdown tables
  pages/               rendered page images and vector single-page PDFs
  tables/p0001_t1.csv  one CSV per table
```

## API

```bash
uvicorn src.api:app --port 8000
curl -F "file=@scan.pdf" "http://localhost:8000/extract?max_pages=3"
```

The endpoint runs the CPU work in a worker thread, enforces `MAX_UPLOAD_MB`, checks
the PDF magic bytes, and persists results under `data/structured/uploads/<job_id>/`.
Poll `GET /jobs/<job_id>` for the result. If `DOCINTEL_API_TOKEN` is set, send
`X-API-Token`.

## Validation

- `source_page` and `source_page_label` are recorded.
- Table column and row sums are checked where a clear total exists.
- Subtotal/`less`/`add` rows are excluded from the sum where recognised.
- `verified` / `arithmetic_ok` / `needs_review` are advisory, not silent corrections.
- Missing values remain `null`; a dash/Nil is marked `nil`.

## Tested examples

| Page | Route | Result |
|---|---|---|
| Reliance FY26 P&L p101 (digital) | native text + Docling vector tables | 18.5 s cold start, 2 tables |
| HDFC FY26 P&L p472 (digital) | native text + native table | 1 table, no OCR |
| HDFC annual p43 (image-only) | Tesseract | 3.1 s total, mean confidence 74.2 |
| Image-only benchmark pages | Tesseract first; Paddle only if confidence is low | measured in `data/benchmark/` |

The hybrid benchmark on image-only pages is stored in
`data/benchmark/hybrid_results.json`. Numeric F1 is 1.00 on the sampled statements;
table-cell recall is 1.00 where a native gold table exists. Latency is dominated by
Docling/Paddle on hard pages, so use Tesseract-first routing and multiple workers
for throughput.
