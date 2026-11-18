# Indian Corporate Document Intelligence — Executive Report

Execution date: **2026-11-14** · Self-hosted open-source stack · No paid APIs

## 1. Executive summary

- **10 companies**, **30 documents**, **4,709 pages** collected and parsed.
- **411 structured fields** with page-level provenance; 100.0% of documents parsed successfully.
- Native parsing ran at **2.904 pages/s**; 158 image-only pages needed OCR fallback.
- Curated source-transcription check: **51/51 fields** matched; **51/51 source pages** correct.
- Highest capability-normalised score: **tesseract** (numeric F1 0.932, key-number recall 1.000, median 1.7 s/page).
- Best text-only engine: **tesseract** (numeric F1 0.932, CER 0.206, 1.7 s/page).
- Best table extraction: **docling** (statement-page numeric cell recall 0.843, structure 0.784).
- Fastest: **tesseract** at 1.75 s/page.
- olmOCR could not be run on this Apple Silicon host (CUDA/vLLM only); Unstructured is an orchestration layer, not a standalone OCR engine. Both are documented, not ranked.

## 2. Ten companies and documents successfully collected

| Company | Annual report (pages) | Quarterly result (pages) | Presentation (pages) |
|---|---:|---:|---:|
| Reliance Industries Limited | 147 | 42 | 68 |
| HDFC Bank Limited | 629 | 17 | 45 |
| Tata Consultancy Services Limited | 360 | 22 | 24 |
| ICICI Bank Limited | 349 | 16 | 65 |
| Infosys Limited | 383 | 20 | 34 |
| Larsen & Toubro Limited | 754 | 10 | 35 |
| ITC Limited | 416 | 6 | 41 |
| Tata Motors Limited | 488 | 6 | 21 |
| Sun Pharmaceutical Industries Limited | 344 | 4 | 14 |
| Bharti Airtel Limited | 271 | 19 | 59 |
| **Total** | **4141** | **162** | **406** |

Document periods are resolved from `data/manifests/`; the annual report label is `FY2025-26 (year ended 31 March 2026)`. Every URL, SHA-256, download date and page count is in the manifest. No document is fabricated.

## 3. OCR engines tested

| Engine | Version | Ran? | Note |
|---|---|---|---|
| Tesseract | 5.5.4 | yes | CPU baseline, 20/20 pages |
| PaddleOCR | 3.7.0 PP-OCRv6 | yes | CPU, 20/20 pages; best numeric recall, slowest |
| Docling | 2.150.0 | yes | layout + TableFormer, 20/20 pages |
| MinerU | 3.0.9 pipeline | yes | CPU pipeline, 20/20 pages |
| OCRmyPDF | 17.14.1 | yes | 20/20 image-only; signed originals refused |
| olmOCR | 0.4.27 | no | blocked: CUDA/vLLM only |
| Unstructured | latest | no | orchestration layer; hi_res stack not installed |

## 4. Benchmark results and rankings

| Rank | Engine | Group | Numeric F1 | Key-number recall | Table cell recall | Table structure | CER | WER | Median s/page | Peak RSS MB | Failures |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | tesseract | text-only | 0.932 | 1.000 | 0.000 | 0.000 | 0.206 | 0.453 | 1.7 | 186 | 0 |
| 2 | ocrmypdf | text-only | 0.927 | 1.000 | 0.000 | 0.000 | 0.229 | 0.482 | 2.9 | 256 | 0 |
| 3 | paddleocr | text-only | 0.978 | 1.000 | 0.000 | 0.000 | 0.324 | 0.557 | 43.7 | 7272 | 0 |
| 4 | docling | table-capable | 0.931 | 0.964 | 0.579 | 0.640 | 0.272 | 0.520 | 9.2 | 3334 | 0 |
| 5 | mineru | table-capable | 0.829 | 0.964 | 0.566 | 0.684 | 0.282 | 0.455 | 36.7 | 3118 | 0 |

Ranking score = 0.45·numeric F1 + 0.30·table-cell recall + 0.15·(1−CER) + 0.10·1/(1+median s), renormalised for text-only engines that do not emit table grids. Text-only and table-capable results are shown separately. The benchmark uses 20 pages. Gold text is the publisher's native text layer, rendered at 200 DPI. Full method: `reports/benchmark_methodology.md`.

### Extended 100-page set

- ocrmypdf F1 0.832 ±0.046; tesseract F1 0.821 ±0.048; docling F1 0.790 ±0.053. See `reports/benchmark_extended.md`.
- PaddleOCR and MinerU remain on the 20-page set because a 100-page pass is roughly 1–1.5 hours per engine on this host.

Degraded-scan robustness (150 DPI, JPEG q50, 0.7° rotation, Gaussian noise; Tesseract only): CER 0.266, WER 0.574, numeric F1 0.917, numeric recall 0.916 over 8 statement pages.

### Company-by-company benchmark quality

| Company | Pages | Best engine | Numeric F1 | CER |
|---|---:|---|---:|---:|
| Bharti Airtel Limited | 2 | paddleocr | 0.980 | 0.770 |
| HDFC Bank Limited | 2 | ocrmypdf | 0.985 | 0.147 |
| ICICI Bank Limited | 2 | mineru | 0.997 | 0.186 |
| Infosys Limited | 2 | paddleocr | 0.934 | 0.137 |
| ITC Limited | 2 | paddleocr | 0.992 | 0.206 |
| Larsen & Toubro Limited | 2 | paddleocr | 0.997 | 0.089 |
| Reliance Industries Limited | 2 | paddleocr | 0.967 | 0.791 |
| Sun Pharmaceutical Industries Limited | 2 | paddleocr | 0.978 | 0.154 |
| Tata Motors Limited | 2 | paddleocr | 0.987 | 0.368 |
| Tata Consultancy Services Limited | 2 | paddleocr | 0.969 | 0.143 |

Table-cell recall is only defined for engines that emit table grids; text-only engines are ranked separately rather than being assigned zero table accuracy.

### Acceptance targets vs measured results

- Clean-scan OCR: best numeric recall **98.9%** (paddleocr); best character accuracy **79.4%**. The character-accuracy target is not met on this corpus.
- Difficult scans: numeric F1 **91.7%**, numeric recall **91.6%** against 95% — not met on this simulated set.
- Table cell accuracy: best **84.3%** on the 10 consolidated statement pages; structure similarity **78.4%**. The structure target is not met.
- Financial numerical exact-match: **100.0%** on the curated source-transcription set; this is not a double-blind human annotation study.
- Source-page traceability: **100%** of fields have a document and page; the curated check found **51/51** correct pages.

## 5. Company-wise extracted financial data

Full tables: `reports/company_financials.md`; per-company CSV/Excel: `company_datasets/<company>/`.

Key consolidated figures (all monetary values normalised to INR crore):

| Company | Revenue/total income | EBITDA | PAT | EPS | Total assets | Equity | CFO |
|---|---:|---:|---:|---:|---:|---:|---:|
| Reliance Industries Limited | 1,075,675 | 207,911 | 95,754 | 59.69 | 2,178,140 | 1,085,866 | 192,113 |
| HDFC Bank Limited | 495,463 | — | 76,026 | 49.50 | 4,908,041 | 608,444 | 113,506 |
| Tata Consultancy Services Limited | 267,021 | 72,274 | 49,454 | 136.01 | 182,372 | 108,478 | 52,094 |
| ICICI Bank Limited | 312,118 | — | 54,208 | 75.89 | 2,914,498 | 379,571 | 67,325 |
| Infosys Limited | 178,650 | 45,313 | 29,474 | 71.58 | 155,967 | 93,297 | 33,986 |
| Larsen & Toubro Limited | 285,874 | 33,189 | 18,954 | 116.93 | 452,550 | 128,530 | 16,741 |
| ITC Limited | 89,913 | 29,829 | 21,018 | 16.52 | 93,792 | 72,873 | 18,464 |
| Tata Motors Limited | 83,855 | 7,482 | 3,030 | 8.23 | 52,309 | 12,734 | 14,981 |
| Sun Pharmaceutical Industries Limited | 58,462 | 18,396 | 11,509 | 47.80 | 108,785 | 83,880 | 12,419 |
| Bharti Airtel Limited | 210,973 | 119,439 | 33,823 | 45.96 | 552,152 | 195,963 | 122,230 |

Quarterly revenue, PAT, EPS and bank ratios are in `reports/company_financials.md`.

## 6. Data quality and error analysis

- Provenance checks (page/text/hash present): **1233/1233**.
- Unit-arithmetic issues: **0**.
- Independent arithmetic checks: **19/20**.
- Records flagged for manual review: **294**. These have a valid source page but no independent arithmetic check; they are not known errors.
- The review queue is in `data/review_queue.csv` (and `review_queue.json`); `python -m src.review apply` records decisions without editing source PDFs.
- Missing values stay `null` or appear in `data/coverage_matrix.csv` as `not_extracted`; they are never silently replaced with zero. A dash/Nil is recorded as `nil`, not as a missing value.
- Balance-sheet identity, PBT−tax=PAT and NII=interest income−interest expense are checked where the input rows are available. Derived values carry `value_status=derived` and a formula.
- Bank PBT is not fabricated. Where the P&L has no PBT line, the extractor emits `profit_before_minority` and labels it derived.
- HDFC Bank equity includes the reported `Employees stock options / units outstanding` line; the earlier ground-truth value omitted it and was corrected to 608,444.43 crore.
- Unit labels are canonical INR crore; `source_value`, `source_unit` and `scale_factor` preserve the printed number. The earlier million/thousand label mismatch is fixed.
- Airtel's Q2 PDF has a low-quality vendor OCR text layer; the extractor re-OCRs that page.
- Pandera master-schema validation: **passed**.
- No independent double-blind human annotation was possible; the 51-field check is a source transcription with arithmetic verification.

## 7. Best free open-source stack

**Recommended:** PyMuPDF (native text + tables) → **Tesseract** for ordinary scans → **Docling** for dense statement/table pages → **PaddleOCR** only when numeric confidence is low. PostgreSQL + Redis/Celery + MinIO + FastAPI for orchestration. Everything is self-hosted and zero-cost.

- Best numeric fidelity: **PaddleOCR**.
- Best speed/lightness: **Tesseract**.
- Best table reconstruction: **Docling**.
- The production extractor now uses the tiered order above instead of sending every scan through PaddleOCR.

## 8. Hardware and performance requirements

- Native path: 4 vCPU / 8 GB / 100 GB SSD.
- OCR path: 16 vCPU / 64 GB for 4 PaddleOCR workers (about 7 GB peak each); Tesseract workers are much lighter and should handle ordinary scans.
- Burst 3,000 OCR pages/day: 8 workers or a 24–48 GB NVIDIA GPU.
- Full detail: `reports/hardware.md` and `reports/production_architecture.md`.

## 9. Production architecture recommendation

FastAPI ingest → SHA-256 dedup → MinIO originals → Celery router → CPU workers (PyMuPDF, Tesseract, Docling) and optional GPU workers → Pandera validation → PostgreSQL field store + Parquet exports. Route digital pages away from OCR; escalate only ambiguous or table-heavy pages. Keep every value tied to `source_document`, `source_page`, `source_page_label`, `source_text` and `source_sha256`.

Smoke-tested: Compose Postgres/Redis/API/worker/chat; `/health`, `/stats`, `/review/queue`, `/extract` and `/jobs/{id}` returned 200. Image size is ~4.8 GB (CPU-only torch).

Not proven: sustained 1,000 pages/day under concurrent load, GPU throughput, and multi-tenant security. A load test is required before calling this production-ready.

## 10. Deliverables

- Master dataset: `data/master_dataset.csv`, `.parquet`, `.xlsx`, `data/coverage_matrix.csv`
- Company summary: `data/master_company_summary.csv|xlsx`
- Company packages: `company_datasets/<slug>/` (JSON, CSV, Excel, Markdown, validation, coverage)
- Benchmark: `data/benchmark/engine_summary.csv`, `page_metrics.csv`, `degraded_metrics.csv`, raw JSONL
- Engine research: `reports/engine_research.json`, `reports/ocr_engine_research.md`
- Dashboard: `reports/dashboard.md`, `reports/dashboard.json`
- Code/API/Docker: `src/`, `docker-compose.yml`, `Dockerfile`, `requirements.txt`, `db/schema.sql`
