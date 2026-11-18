# Benchmark methodology

## Page selection

`data/benchmark/pages.json` contains 20 pages:
- 10 consolidated statement-of-profit-and-loss pages (one per company);
- 10 narrative pages selected from the annual report for high text density, low digit ratio and
  length 900–3,000 characters.

Each page is rendered at 200 DPI (`PyMuPDF`), and a single-page image-only PDF is built. Every
engine therefore receives exactly the same pixels. The original digital page supplies the gold text
and gold table grid.

**Integrity check:** all 20 benchmark PDFs were verified to contain **zero native text** before the
final run. An earlier build accidentally retained vector pages for some samples, which gave
Docling/MinerU an unfair text-layer advantage; those runs were discarded and Docling, MinerU and
OCRmyPDF were re-run on the corrected image-only assets. Tesseract/PaddleOCR always consumed the
rendered PNG, so their results were unaffected.

## Extended 100-page set

`benchmark/build_extended.py` selects ten pages per annual report: statement pages, dense
notes/table pages and narrative pages. The extended manifest is `manifest_extended.json`; assets are
under `data/benchmark/pages_extended/`. Tesseract is run 3× and OCRmyPDF 2× on this set; Docling is
run once. PaddleOCR and MinerU remain on the 20-page set because a 100-page run would take roughly
1–1.5 hours per engine on this host. Results are in `engine_summary_extended.csv` and
`reports/benchmark_extended.md`.

## Engines and versions

| Engine | Version | Input | Models |
|---|---|---|---|
| Tesseract | 5.5.4 | PNG | eng traineddata |
| PaddleOCR | 3.7.0 / paddlepaddle 3.3.1 | PNG | PP-OCRv6_medium det+rec |
| Docling | 2.150.0 | single-page PDF | layout heron, TableFormerV2 |
| MinerU | 3.0.9 | single-page PDF | PDF-Extract-Kit-1.0, pipeline backend, en |
| OCRmyPDF | 17.14.1 | single-page PDF | Tesseract wrapper |
| olmOCR | 0.4.27 | — | blocked: needs CUDA/vLLM |

Model load is measured separately (`load_s`); the first page includes any lazy warm-up. Latency is
wall-clock per page in one process per engine. Peak RSS is `ru_maxrss` for the engine process and its
children, so subprocess engines (MinerU, OCRmyPDF) are not reported as the parent client's memory.

## Metrics

- **CER / WER**: `jiwer` on Markdown-stripped, whitespace-normalised lower-case text. Markdown
  headings/bold markers are formatting, not OCR accuracy, and are removed before scoring.
- **Numeric P/R/F1**: signed multiset matching of numeric tokens after comma removal, parenthesis
  negation and 2-decimal rounding. Header-only year rows are ignored; signs are preserved so a loss
  cannot match a profit.
- **Key-number recall**: presence of the company's reported revenue, PBT, PAT, total assets and CFO
  on the statement page, using a relative tolerance of 0.05%. The target unit is derived from the
  page header, not hard-coded per company.
- **Line-order similarity**: `difflib.SequenceMatcher` over normalised non-empty lines.
- **Table cell recall**: numeric cells matched against the best corresponding native table.
- **Table text recall**: normalised non-empty cell text matched against the gold table.
- **Table structure similarity**: row/column/cell-count agreement; it is a structural proxy, not a
  TEDS/GriTS score.
- **Table extra-table penalty**: unmatched engine tables are counted in the precision denominator.
- **Failure rate**: non-zero exit, empty output, engine exception, with one retry.

## Ranking

`rank_score = 0.45 × numeric_F1 + 0.30 × table_cell_recall + 0.15 × (1 − CER) + 0.10 × 1/(1+median_s)`.

Text-only engines cannot produce table grids. They are labelled `rank_group=text-only` and their
weights are renormalised rather than treating "no table output" as zero table accuracy. The report
shows the text-only and table-capable groups separately.

## Ground truth limitation

The gold text is the publisher's embedded text layer, not an independent human transcription. That is
appropriate for measuring OCR fidelity on digitally born filings, but it does not measure errors
already present in the publisher's PDF. A separate 51-field source-transcription check covers three
companies and is documented in `data/ground_truth/manual_verification.json`. The HDFC equity value
in that check was corrected to include the reported ESOP line (4,545.11 crore).
