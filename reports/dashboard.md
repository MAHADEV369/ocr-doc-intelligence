# Results dashboard — Indian corporate document intelligence

Generated: 2026-11-14

| Metric | Value |
|---|---|
| Companies processed | 10 |
| Documents collected | 30 |
| Total pages collected | 4709 |
| Pages parsed (all) | 4709 |
| Pages OCR'd (scanned/image-only fallback) | 158 |
| Structured fields extracted | 411 |
| Document success rate (%) | 100.0 |
| Total native parse time (s) | 1621.4 |
| Native parse throughput (pages/s) | 2.904 |
| Curated source-transcription accuracy | 1.0 |
| Source-page traceability | 1.0 |
| Provenance checks passed | 1233 |
| Provenance checks total | 1233 |
| Independent arithmetic checks passed | 19 |
| Independent arithmetic checks total | 20 |
| Pandera master-schema validation passed | True |
| Records flagged for manual review | 294 |
| Best statement-page table-cell recall | 0.8429 |
| Best statement-page table engine | docling |
| Failed documents | 0 |

## Engine ranking

| Rank | Engine | Group | Numeric F1 | Key-number recall | Table cell recall | CER | Median s/page | Peak RSS (MB) |
|---|---|---|---|---|---|---|---|---|
| 1 | tesseract | text-only | 0.932 | 1.000 | 0.000 | 0.206 | 1.75 | 186 |
| 2 | ocrmypdf | text-only | 0.927 | 1.000 | 0.000 | 0.229 | 2.91 | 256 |
| 3 | paddleocr | text-only | 0.978 | 1.000 | 0.000 | 0.324 | 43.71 | 7272 |
| 4 | docling | table-capable | 0.931 | 0.964 | 0.579 | 0.272 | 9.15 | 3334 |
| 5 | mineru | table-capable | 0.829 | 0.964 | 0.566 | 0.282 | 36.66 | 3118 |
