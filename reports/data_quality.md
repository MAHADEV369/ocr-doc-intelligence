# Data quality and failure analysis

## Coverage by company

| Company | Annual fields | Quarterly fields | Bank-ratio fields | Provenance checks | Independent arithmetic checks |
|---|---:|---:|---:|---:|---:|
| Reliance Industries Limited | 30 | 7 | 0 | 111/111 | 2/2 |
| HDFC Bank Limited | 29 | 11 | 7 | 141/141 | 1/2 |
| Tata Consultancy Services Limited | 28 | 12 | 0 | 120/120 | 2/2 |
| ICICI Bank Limited | 29 | 13 | 7 | 147/147 | 2/2 |
| Infosys Limited | 25 | 12 | 0 | 111/111 | 2/2 |
| Larsen & Toubro Limited | 29 | 12 | 0 | 123/123 | 2/2 |
| ITC Limited | 30 | 12 | 0 | 126/126 | 2/2 |
| Tata Motors Limited | 29 | 12 | 0 | 123/123 | 2/2 |
| Sun Pharmaceutical Industries Limited | 30 | 4 | 0 | 102/102 | 2/2 |
| Bharti Airtel Limited | 31 | 12 | 0 | 129/129 | 2/2 |

Provenance checks cover source page, source text and source SHA-256. Independent arithmetic checks
cover the balance-sheet identity, PBT−tax=PAT and NII=interest income−interest expense where the
inputs exist. They are reported separately: a page-number check is not an accuracy check.
HDFC's balance-sheet identity check is deliberately marked not independent because the two "Total"
rows come from the same source line; the other check there is PBT-related and does not apply to a
bank P&L without a PBT line.

## Corrections in this run

1. **HDFC Bank equity now includes ESOP.** The balance sheet reports
   `Employees stock options / units outstanding` of 4,545.11 crore. The earlier value (603,899.32)
   omitted it; the corrected total is **608,444.43 crore**, and total liabilities is 4,299,596.41.
2. **Unit labels are canonical.** Values printed in million/thousand/lakh are converted to
   **INR crore** and keep `source_value`, `source_unit` and `scale_factor`. The earlier build stored
   the crore value under an `INR million`/`INR thousand` label.
3. **Thousands and lakhs are detected correctly.** The old code replaced every letter `h` with the
   rupee symbol, turning `thousand` into `t₹ousand` and `lakh` into `lak₹`.
4. **Bank PBT is not fabricated.** HDFC and ICICI do not report a PBT line in their statutory P&L;
   total income minus total expenditure is profit after tax before minority/associates. It is stored
   as `profit_before_minority` with `value_status=derived`, not as `pbt`.
5. **Missing values are explicit.** `data/coverage_matrix.csv` lists every expected company/field
   combination with `not_extracted` where no row was produced. A dash/Nil is `nil`, not a missing
   value and not an unexplained zero.
6. **Pandera validates the master table.** Types, allowed statuses, unit arithmetic and page bounds
   are checked in `data/pandera_report.json`.

## Known issues and how they were handled

1. **Bharti Airtel Q2 PDF has a vendor OCR text layer.** The page looks digital (it has characters)
   but contains corrupted words. The quarterly extractor detects the quality failure and re-OCRs the
   page with Tesseract at 300 DPI.
2. **TCS trade receivables ambiguity.** The statement page contains a small note-like row and a large
   main row with the same label. The extractor selects the larger consolidated row (INR 57,630 crore);
   the source text shows the exact row.
3. **HDFC/ICICI quarterly vs annual basis.** Annual fields are consolidated. The HDFC Q2 presentation
   is explicitly standalone; the ICICI capital-adequacy slide is consolidated. The bank-ratio dataset
   records `reporting_basis` per field.
4. **Sun Pharma Q2 source is a press release.** It states sales, EBITDA, PBT and net profit in prose.
   Those four fields use the exact sentence as provenance; EPS is left null rather than inferred.
5. **Reliance Q2 source is the official media release.** Revenue, EBITDA, PBT, PAT and tax are
   extracted from the consolidated highlights table.
6. **TCS/Infosys borrowings and inventory are null.** The companies report no such line in the
   consolidated statements; the coverage matrix records `not_extracted`, not zero.
7. **HDFC provision coverage is null.** The Q2 presentation does not disclose a PCR; no proxy is
   invented.
8. **OCRmyPDF and signed PDFs.** OCRmyPDF refuses to alter digitally signed files; production must
   strip signatures or OCR a rendered copy. The benchmark uses image-only pages, where it passed.
9. **olmOCR is not runnable here.** vLLM requires CUDA; the host is Apple Silicon.
10. **Unstructured is not a standalone OCR engine.** Its `hi_res` path delegates OCR to
    Tesseract/PaddleOCR; it is documented, not ranked.

## Human review queue

`data/review_queue.csv` contains the 294 fields whose validation status is `needs_review`, with a stable
`review_id`, priority, value, source page and source text. Decisions are recorded in
`data/review_decisions.json` and applied on the next export; the source PDFs are never modified.

## Validation logic

- Every field must have a source document and page; provenance count is 100%.
- Every monetary field must satisfy `normalized_value = source_value × scale_factor`; unit issues
  count is zero.
- Balance-sheet identity: total assets = total equity and liabilities (tolerance 0.5%), but not when
  both values came from the same source row.
- PBT − tax = PAT (tolerance 2%) where an industrial company reports all three rows.
- NII = interest income − interest expense for banks.
- EBITDA / EBIT / FCF / total liabilities / equity / profit_before_minority show a formula and
  `value_status=derived`.
- `needs_review` means no independent arithmetic check applied; it is not an error flag.

## Benchmark gold-standard limitation

The benchmark gold text is the publisher's embedded text layer, verified against rendered pages. It
is authoritative for measuring OCR fidelity on digitally born filings but is not an independent human
transcription. The 51-field source-transcription check is included as a separate traceability test;
it is not a substitute for a double-blind annotation study.
