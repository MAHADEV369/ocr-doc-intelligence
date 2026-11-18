# Indian Corporate Document Intelligence Benchmark

A self-hosted, open-source pipeline that ingests annual reports, quarterly results and investor
presentations from ten Indian listed companies, extracts financial statements with page-level
provenance, and benchmarks four OCR/document-parsing engines on the same rendered pages.

**Execution date:** 14 November 2026 · **Documents:** 30 · **Pages:** 4,709 · **Companies:** 10

> **Repository contents:** this public repository ships the source code, tests, Docker files and
> reports only. Generated datasets (`data/`), source PDFs, page images, company packages and the
> deliverable ZIP are intentionally excluded because of size and source-document licensing. Run the
> pipeline locally to regenerate them; a full run writes `data/manifests/` with every source URL,
> SHA-256 and page count.

---

## 1. What was built

```
data/raw/<company>/            original PDFs (never modified)
data/manifests/<company>.json  source URLs, SHA-256, page counts
data/parsed/<company>/<type>/  page-level JSONL + Markdown + tables
data/structured/               financial fields, bank ratios, document profiles
data/benchmark/                rendered pages, gold text, raw engine output, metrics
company_datasets/<company>/    per-company CSV / Excel / JSON / Markdown / validation
data/master_dataset.csv|parquet|xlsx
src/                           ingestion, parsing, extraction, validation, export, API
benchmark/                     page builder, engine runners, metrics
docker-compose.yml             API + worker + Postgres + Redis (MinIO optional)
```

The pipeline:

1. Downloads and preserves each source PDF, computes SHA-256 and page count.
2. Profiles every page as digital / mixed / scanned / blank.
3. Extracts native text with PyMuPDF; falls back to Tesseract OCR on 158 image-only pages.
4. Detects and reconstructs tables with PyMuPDF; stores per-page tables and Markdown.
5. Classifies document sections (auditor report, balance sheet, P&L, cash flow, notes, MD&A, ...).
6. Extracts consolidated financial fields with label + visual-row parsing, keeps the exact source
   text and PDF page for every value.
7. Derives EBITDA / EBIT / NII / free cash flow only with an explicit formula, marked `arithmetic_ok`.
8. Validates balance-sheet and PBT/tax/PAT identities; never replaces a missing value with zero.
9. Exports JSON, CSV, Excel, Parquet and a FastAPI service.

## 2. Documents collected

All 30 documents were verified with HTTP 200 + `application/pdf`, downloaded from official company
or stock-exchange sources, hashed, and opened with PyMuPDF. Full provenance is in
`data/manifests/`. Latest annual reports are FY2025-26; quarterly results are Q2 FY2026-27
(quarter ended 30 September 2026).

| Company | Annual report | Quarterly result | Presentation |
|---|---|---|---|
| Reliance Industries | 147 pp | 42 pp | 68 pp |
| HDFC Bank | 629 pp | 17 pp | 45 pp |
| Tata Consultancy Services | 360 pp | 22 pp | 24 pp |
| ICICI Bank | 349 pp | 16 pp | 65 pp |
| Infosys | 383 pp | 20 pp | 34 pp |
| Larsen & Toubro | 754 pp | 10 pp | 35 pp |
| ITC | 416 pp | 6 pp | 41 pp |
| Tata Motors | 488 pp | 6 pp | 21 pp |
| Sun Pharmaceutical | 344 pp | 4 pp | 14 pp |
| Bharti Airtel | 271 pp | 19 pp | 59 pp |
| **Total** | **4,141** | **162** | **406** |

**4,709 pages** in total; every page was parsed, and 158 image-only pages were OCR'd.

## 3. Installation

### macOS (development host used for this run)

```bash
brew install tesseract poppler ghostscript
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

PaddleOCR and Docling download model weights from Hugging Face/PaddleX on first use. MinerU's
first run downloads the PDF-Extract-Kit weights. No paid API key is required.

### Linux / production

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng poppler-utils libgl1 libglib2.0-0 ghostscript
pip install -r requirements.txt
```

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
# API: http://localhost:8000/docs · chat: http://localhost:8001
# Default stack: Postgres, Redis, API, Celery worker, chat. MinIO is optional because the
# public image was unavailable in this environment; set S3_* to use an external S3/MinIO.
```

## 4. Execution

```bash
# 1. ingest + parse + extract + export everything
python -m src.pipeline

# or one company / one stage
python -m src.parse
python -m src.statements reliance
python -m src.quarterly tcs
python -m src.bank_ratios
python -m src.export
python -m src.verify_gt
python -m src.master_summary
python -m src.company_financials
python -m src.dashboard
python -m src.report
python -m src.validation          # Pandera master-table validation
python -m src.review queue         # write data/review_queue.csv/json
python -m src.review apply --id … --status verified --reviewer … --note …
python -m src.store               # optional Postgres/MinIO mirror when configured
make test                         # pytest
make lint                         # ruff

# 2. benchmark (see reports/benchmark_methodology.md)
python -m benchmark.build_pages
python -m benchmark.run_engine --engine tesseract
python -m benchmark.run_engine --engine paddleocr
python -m benchmark.run_engine --engine docling
python -m benchmark.run_engine --engine mineru
python -m benchmark.run_engine --engine ocrmypdf
python -m benchmark.metrics
```

## 4b. Production hybrid extractor (best-results mode)

The single-command tool that combines the measured strengths:

```bash
python -m src.production_extractor data/raw/hdfc/annual_report_fy2026.pdf   -o data/structured/production/hdfc_p472 --start-page 472 --max-pages 1
```

It routes digital pages to PyMuPDF, statement pages to Docling tables, ordinary
scans to Tesseract, and escalates only low-confidence or table-heavy scans to
PaddleOCR. Tables use Docling structure plus OCR cell fusion, row/column
cross-foot checks and page-level provenance. It writes `result.json`,
`document.md` and per-table CSV files. The HTTP equivalent is `POST /extract`
with a multipart PDF upload. Design and measured examples:
`reports/production_extractor.md`.

## 4c. LLM chat tool (web + CLI + MCP)

```bash
# local chat UI with grounded answers and page citations
uvicorn src.chat_app:app --port 8001     # http://localhost:8001

# terminal chat
python -m src.chat_cli

# MCP server for Claude Desktop / any MCP client
python -m src.mcp_server
```

It indexes 30 documents / 4,709 pages / 411 fields. Numeric questions are answered
deterministically from extracted fields; qualitative questions use the local
`qwen3.5:9b` via Ollama, with every number checked against the retrieved evidence.
Tools are also exposed in OpenAI function-calling format at
`tools/openai_tools.json`. Full setup: `reports/llm_chat_tool.md`.

## 5. API

```bash
uvicorn src.api:app --reload
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | record/company counts |
| `GET /companies` | coverage by company |
| `GET /companies/{slug}` | all records for a company |
| `GET /fields?company=&field_name=&financial_year=` | filtered field query |
| `GET /documents` | document manifest (URL, SHA-256, pages) |
| `GET /stats` | validation and engine splits |
| `GET /benchmark` | engine ranking table |
| `POST /extract` | hybrid extraction of an uploaded PDF (job id returned) |
| `GET /jobs/{job_id}` | result of an upload job |
| `GET /review/queue` | fields awaiting human review |
| `POST /review/{review_id}` | record a review decision |

Every field returned includes `source_document`, `source_page`, `source_page_label`, `source_text`,
`source_sha256`, `source_value`, `source_unit`, `scale_factor`, `value_status`, `confidence`,
`validation_status`, `extraction_engine` and `model_version`. Set `DOCINTEL_API_TOKEN` to require
`X-API-Token`; uploads are capped by `MAX_UPLOAD_MB`.

## 6. Data model

The canonical record follows the mission contract:

```json
{
  "company": "Reliance Industries Limited",
  "document_type": "annual_report",
  "financial_year": "FY2025-26",
  "report_period": "Year ended 31 Mar 2026",
  "reporting_basis": "consolidated",
  "field_name": "pat",
  "original_value": "Profit for the year | 95,754 | 81,309",
  "normalized_value": 95754.0,
  "currency": "INR",
  "unit": "INR crore",
  "source_value": 95754.0,
  "source_unit": "INR crore",
  "scale_factor": 1.0,
  "value_status": "reported",
  "is_derived": false,
  "formula": "",
  "source_document": "data/raw/reliance/annual_report_fy2026.pdf",
  "source_page": 101,
  "source_page_label": "101",
  "source_table": "profit_and_loss",
  "source_text": "Profit for the year | 95,754 | 81,309",
  "source_sha256": "…",
  "confidence": 0.92,
  "confidence_method": "label_regex+visual_row",
  "validation_status": "verified",
  "extraction_engine": "native_pymupdf",
  "model_version": "PyMuPDF 1.27.2.2",
  "section": "profit_and_loss",
  "notes": "prior_year_value=81309.0",
  "run_id": "run-…",
  "extracted_at": "2026-11-14T…"
}
```

`NULL`/missing means **not reported or not extractable**; it never means zero. A dash/Nil is
`value_status=nil`. Standalone and consolidated statements are kept separate (`reporting_basis`).
All extracted annual fields use consolidated statements. Monetary values are always normalised to
**INR crore**; `source_value`, `source_unit` and `scale_factor` preserve the printed number.
The full expected-field coverage, including fields that were not extracted, is in
`data/coverage_matrix.csv`.

## 6b. Results at a glance

| Engine | Numeric F1 | Statement-page table recall | CER | Median s/page | Peak RSS |
|---|---:|---:|---:|---:|---:|
| **Docling** | 0.931 | **0.843** | 0.272 | 9.2 | 3.3 GB |
| MinerU | 0.829 | 0.781 | 0.282 | 36.7 | 3.1 GB* |
| Tesseract | 0.932 | n/a | **0.206** | **1.7** | **186 MB** |
| OCRmyPDF | 0.927 | n/a | 0.229 | 2.9 | 256 MB |
| PaddleOCR | **0.978** | n/a | 0.324 | 43.7 | 7.3 GB |

*MinerU runs its models in a local service; memory is now measured for the engine process and its
children rather than the parent client alone.

**Ranking:** Tesseract leads the text-only group; Docling leads the table-capable group. PaddleOCR has
the best numeric fidelity but is ~25× slower than Tesseract and uses ~7 GB of RAM. The capability-
normalised overall score is not a claim that one engine should do every job: the production routing
uses Tesseract first, Docling for tables, and PaddleOCR only when numeric confidence is low.
Acceptance targets were not all met: clean numeric recall reached 98.9% but character accuracy was
79.4%, degraded-scan numeric F1 was 91.7%, and statement-page table structure similarity was 78.4%.
Full results and failures are in `reports/executive_report.md` and `reports/failure_analysis.md`.

The extended **100-page** set (statement, notes-table and narrative pages) has Tesseract F1
0.821 ±0.048 over 3 runs, OCRmyPDF 0.832 ±0.046 over 2 runs and Docling 0.790 ±0.053 over 1 run;
Docling's statement-page table recall is 0.775. PaddleOCR and MinerU remain on the 20-page set
because a 100-page pass takes roughly 1–1.5 hours per engine on this host.

## 7. Benchmark method

Twenty pages are compared: one consolidated P&L page and one narrative page per company. Each page
is rendered at 200 DPI, wrapped in a single-page image-only PDF, and passed to every engine. The
publisher's native text layer is the gold text (these are digitally born filings; no independent
human annotation was available). Metrics: Markdown-neutral CER/WER, **signed** numeric-token
precision/recall/F1, key financial number recall, line-order similarity, numeric and text table-cell
recall, table structure similarity, latency and peak RSS for the engine process **and children**.
Text-only engines are ranked separately from table-capable engines. See
`reports/benchmark_methodology.md`.

## 7b. Corrections in the current dataset

- All monetary values are normalised to **INR crore**; `source_value`, `source_unit` and `scale_factor`
  preserve the printed number. The earlier build stored crore values under `INR million`/`INR thousand`
  labels.
- `thousand` and `lakh` unit headers are detected correctly; the old `h`-replacement corrupted both words.
- HDFC Bank equity now includes the reported ESOP line: **608,444.43 crore** (not 603,899.32).
- HDFC and ICICI do not report a statutory PBT line. The derived profit-after-tax-before-minority value
  is stored as **`profit_before_minority`**, not as `pbt`.
- A dash/Nil is `value_status=nil`; an expected but absent field appears in
  `data/coverage_matrix.csv` as `not_extracted`, not as zero.
- Provenance checks and independent arithmetic checks are reported separately; the old single
  “428/428” number mixed page-presence checks with a handful of arithmetic checks.
- `data/pandera_report.json` validates the master table types, statuses, unit arithmetic and page bounds.

## 8. Key limitations

- olmOCR could not run: vLLM requires CUDA; this host is Apple Silicon with 16 GB unified memory.
- Unstructured is an orchestration layer, not a standalone OCR engine on this host; it was not ranked.
- OCRmyPDF passed 20/20 image-only benchmark pages. On the **original signed PDFs** it refuses to
  alter digitally signed files (observed during the first run), so production must strip signatures
  or OCR a rendered copy first. Failures are reported, not hidden.
- Bharti Airtel's Q2 PDF has a low-quality vendor OCR text layer. The pipeline detects this and
  re-OCRs the page with Tesseract before extraction.
- The "ground truth" is a source transcription cross-check (51 fields, 3 companies), not a
  double-blind human study. It validates arithmetic and traceability, not independent annotation.
- Peak RAM on this 16 GB host reached ~6.8 GB for PaddleOCR; production sizing is in
  `reports/production_architecture.md`.
- The public MinIO image was unavailable during this run. Compose starts Postgres + Redis; `src.store`
  still supports an external S3/MinIO endpoint when `S3_ENDPOINT` is configured.

## 9. Licences

Code: Apache-2.0 / MIT components. MinerU model weights are AGPL-3.0 and MinerU code has additional
commercial terms; review before commercial deployment. Details in `reports/engine_research.json`.
