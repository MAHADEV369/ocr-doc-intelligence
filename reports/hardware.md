# Hardware and measured resource use

## Execution host

| Component | Value |
|---|---|
| Machine | Apple Silicon (arm64) |
| CPU cores | 10 |
| RAM | 16 GB unified memory |
| Disk free during run | ~64 GB |
| OS | macOS (darwin) |
| Python | 3.13.5 (Anaconda), PyMuPDF 1.27.2.2 |
| Tesseract | 5.5.2 (leptonica 1.87.0) |
| PaddleOCR | 3.7.0, paddlepaddle 3.3.1, PP-OCRv6 medium |
| Docling | 2.150.0 (layout heron, TableFormerV2) |
| MinerU | 3.0.9 pipeline, PDF-Extract-Kit-1.0 |
| GPU | Apple MPS available; no CUDA |

## Measured figures

- 30 documents / 4,709 pages parsed in **1,626.0 s** total (~27.1 min), i.e. **2.90 pages/s**.
- 158 pages required Tesseract OCR fallback.
- PaddleOCR peak RSS **~7.3 GB**; Tesseract **~186 MB**; OCRmyPDF **~256 MB** including its
  Ghostscript/Tesseract child process; Docling **~3.3 GB**; MinerU **~3.1 GB** including its local
  model service.
- Per-engine latency and accuracy: `data/benchmark/engine_summary.csv`.
- Memory is measured for the engine process **and its children**; earlier runs reported only the
  parent client for MinerU/OCRmyPDF.
- Source PDFs: 228 MB; workspace after derivatives: see `du -sh data company_datasets`.

## Extended 100-page set

| Engine | Median s/page | Peak RSS | Runs |
|---|---:|---:|---:|
| Tesseract | 1.61 | 177 MB | 3 |
| OCRmyPDF | 3.02 | 292 MB | 2 |
| Docling | 7.22 | 2.6 GB | 1 |

PaddleOCR and MinerU were not run on the extended set; their 20-page results remain in
`data/benchmark/engine_summary.csv`.

## Sizing guidance

### Minimum development / small team

- 8 vCPU, 16 GB RAM, 100 GB SSD.
- Runs native parsing and Tesseract; PaddleOCR one page at a time (slow but works).
- 1,000 digital pages/day easily; 200–400 OCR pages/day.

### Recommended production (CPU)

- 16 vCPU, 64 GB RAM, 1 TB NVMe.
- 4 PaddleOCR workers (4 × ~7 GB) + API + Postgres + Redis.
- 1,000–2,000 mixed pages/day; burst 3,000 with queued backpressure.
- Tesseract workers for cheap scans; Docling for table pages.

### GPU option

- 24–48 GB NVIDIA GPU (RTX 4090 / L40S / A6000 Ada), 32 vCPU, 128 GB RAM.
- Docling/MinerU VLM and olmOCR become viable; olmOCR 7B needs ~15 GB weights plus KV cache.
- Best for dense scanned financial statements and multi-column layouts.

### Container image

- `ocr-api:latest` is **4.78 GB** (CPU-only torch; benchmark-only MinerU is excluded from the API image).
- Compose smoke test: Postgres, Redis, API, Celery worker and chat all started; API `/health`, `/stats`, `/review/queue`, `/extract`, `/jobs/{id}` and chat `/api/health` returned 200.

## Storage

- 50 KB/page original; 150–250 KB/page with page images and JSON.
- 1,000 pages/day → ~50–75 GB/year raw, ~200 GB/year with all derivatives and backups.
- PostgreSQL metadata is small (hundreds of MB for millions of fields).
