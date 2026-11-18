# Extended benchmark (100 pages)

Pages: **100** · Runs per engine: **3** · Engine-page runs: **600**

| Engine | Group | Numeric F1 | 95% CI | CER | 95% CI | Table cell recall (statement) | Table structure | Median s/page | Peak RSS MB | Runs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tesseract | text-only | 0.821 | ±0.048 | 0.331 | ±0.045 | 0.000 | 0.000 | 1.61 | 177 | 3 |
| ocrmypdf | text-only | 0.832 | ±0.046 | 0.331 | ±0.046 | 0.000 | 0.000 | 3.02 | 292 | 2 |
| docling | table-capable | 0.790 | ±0.053 | 0.335 | ±0.044 | 0.775 | 0.737 | 7.22 | 2619 | 1 |

The extended set is stratified across the ten annual reports: statement pages, dense notes/table pages and narrative pages. Gold text remains the publisher's native text layer, not an independent human transcription. CIs are 95% page-level intervals (1.96 × standard error across pages).

Failures: docling tatamotors notes_table p9

PaddleOCR and MinerU were not run on the extended set: at ~44 s/page and ~37 s/page respectively, a 100-page pass would take 1–1.5 hours per engine on this host. Their 20-page benchmark results remain in `engine_summary.csv`.
