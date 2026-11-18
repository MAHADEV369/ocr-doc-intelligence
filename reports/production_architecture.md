# Production architecture recommendation

## Design goals

- 1,000 pages/day sustained, 3,000 pages/day burst.
- Zero mandatory paid APIs; all processing local.
- Page-level provenance for every value; no silent zero-filling.
- Deterministic routing: digital pages never pay an OCR cost.

## Recommended topology

```
                    ┌────────────────────────────┐
 PDFs / uploads ───►│ FastAPI ingest + SHA-256   │
                    └─────────────┬──────────────┘
                                  │ MinIO (originals, parsed, exports)
                    ┌─────────────▼──────────────┐
                    │ PostgreSQL (metadata,      │
                    │ fields, validation runs)   │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │ Redis + Celery queues      │
                    │  route: digital | scanned  │
                    └──────┬──────────────┬──────┘
                           │              │
              ┌────────────▼───┐   ┌──────▼─────────────┐
              │ CPU workers    │   │ GPU workers        │
              │ PyMuPDF/Tika   │   │ Docling / MinerU   │
              │ Tesseract      │   │ PaddleOCR / VLM    │
              │ PaddleOCR      │   │ (optional)         │
              └────────────┬───┘   └──────┬─────────────┘
                           └───────┬──────┘
                    ┌──────────────▼─────────────┐
                    │ Validation + export        │
                    │ Pandera / Polars / Arrow   │
                    └────────────────────────────┘
```

## Routing policy

1. **Digital page** (native characters ≥ 120): PyMuPDF text + table finder. This covers ~97.7% of
   the 4,709 collected pages. No OCR, no GPU.
2. **Image-only page**: Tesseract for fast OCR; if the page has a table or the Tesseract numeric
   confidence is low, escalate to PaddleOCR (best numeric recall in this benchmark) or Docling
   (best table reconstruction).
3. **Dense financial statement page**: Docling with TableFormer for layout + table HTML, then the
   rules-based statement extractor. Keep the native text parser as a cross-check.
4. **Hard/scanned page or vendor-OCR garbage**: re-OCR at 250–300 DPI; if a GPU is available,
   MinerU/olmOCR can be used as a third opinion. Disagreement is flagged for review, not averaged.
5. **Bank statements**: use the bank schema (interest income/expense, NII, deposits, advances, GNPA,
   NNPA, PCR, CASA, CAR, NIM), never industrial EBITDA labels.

## Capacity math (measured on this host)

- Native parse: **2.90 pages/s** single process (4,709 pages in 1,626 s including 158 OCR fallback pages).
- PaddleOCR: **~44 s/page**, peak RSS ~7.3 GB/process (PP-OCRv6 medium, 200 DPI).
- Tesseract: **~1.7 s/page**, ~186 MB RSS.
- Docling: see `data/benchmark/engine_summary.csv`; ~9.2 s/page warm, ~3.3 GB peak.
- MinerU pipeline: each CLI invocation starts a local service; budget ~30–60 s/page on CPU.

| Target | Native path | OCR-heavy path |
|---|---|---|
| 1,000 pages/day | 5 minutes on 1 process | 12.2 CPU-hours; 4 workers ≈ 3.1 h |
| 3,000 pages/day | 14 minutes on 4 processes | 36.7 CPU-hours; 8 workers ≈ 4.6 h |
| Burst 3,000/day | scale stateless API workers | 8–12 OCR workers, 64 GB RAM, or 2× 24 GB GPUs |

A 16-vCPU / 64 GB CPU node with 4 PaddleOCR workers covers 1,000–2,000 mixed pages/day. For a
guaranteed 3,000 OCR pages/day, use 8 workers (64 GB) or a 24–48 GB NVIDIA GPU with Docling/MinerU.

## Storage

- 4,709 source pages = 228 MB of original PDFs (~48 KB/page).
- Keep originals + page PNGs + Markdown + JSON + Parquet. Budget ~3–4× the PDF size.
- 1,000 pages/day ≈ 50 MB/day originals; ~55 GB/year with derivatives.
- MinIO buckets (optional; the Compose stack now runs Postgres + Redis only because the public MinIO image was unavailable in this environment): `originals/`, `pages/`, `parsed/`, `structured/`, `exports/`.
- PostgreSQL stores hashes and field-level rows; Parquet is the analytical source of truth.

## Reliability

- SHA-256 deduplication before any processing.
- Idempotent Celery tasks keyed by `(sha256, page, engine, model_version)`.
- Retry with exponential backoff; preserve failure reason in `documents.status`.
- Never overwrite a failed parse with an empty result; keep the original.
- Validation gates: source page present, data type, balance-sheet identity, PBT−tax=PAT, NII identity.
- Flag, do not auto-correct, values that fail identity checks.

## Security and compliance

- Fully self-hosted; no document leaves the network.
- MinIO SSE-S3 or volume encryption; PostgreSQL TLS in production.
- Role-based access on the API; audit log for exports.
- Respect source terms: store the public filing URL and download date; do not redistribute PDFs
  beyond internal research use without checking the issuer's terms.

## What is proven vs not

Proven in this run: ingestion, hashing, digital/scanned routing, 4,709-page parsing, statement
extraction with provenance, validation, exports, API, and a reproducible 20-page engine benchmark.

Not proven: 1,000 pages/day under sustained load, multi-tenant concurrency, GPU throughput for
olmOCR/MinerU-VLM, and independent human annotation accuracy. A load test with `locust`/`hey` and a
GPU node is the next step before a production go-live.
