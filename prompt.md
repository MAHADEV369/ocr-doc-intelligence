# PROJECT: INDIAN CORPORATE DOCUMENT INTELLIGENCE BENCHMARK
## Mission: Build, execute, benchmark and evaluate a universal open-source document extraction system.

### 1. YOUR ROLE

You are an autonomous team of senior AI engineers, document intelligence researchers, data engineers, financial analysts and quality assurance specialists.

Your assignment is to research, implement and execute a self-hosted document intelligence pipeline using free and open-source GitHub projects.

I do not want a theoretical report, a list of recommendations or an architecture proposal.

I want you to execute the work, process actual documents from real Indian listed companies, generate clean structured datasets, compare OCR engines and present the results.

Make reasonable decisions independently. Do not ask me routine questions. Do not stop after researching repositories.

### 2. OBJECTIVE

Build and evaluate a universal document intelligence pipeline capable of extracting information from:

- Annual reports
- Quarterly financial results
- Investor presentations
- Balance sheets
- Profit and loss statements
- Cash flow statements
- Shareholder letters
- Management commentary
- Corporate announcements
- Research reports
- Scanned documents
- Complex financial tables
- Footnotes and disclosures

The system must support different companies, industries, document layouts and PDF qualities.

Target production capacity: 1,000 pages/day, with 3,000 pages/day burst capacity.

Deployment: Self-hosted.

Budget: Prefer zero-cost open-source software and locally runnable models. No mandatory paid APIs.

### 3. COMPANIES TO PROCESS

Use these 10 Indian listed companies:

1. Reliance Industries
2. HDFC Bank
3. Tata Consultancy Services
4. ICICI Bank
5. Infosys
6. Larsen & Toubro
7. ITC
8. Tata Motors
9. Sun Pharmaceutical Industries
10. Bharti Airtel

Use official investor relations websites, stock exchange filings and other authoritative primary sources.

Select the latest available annual report and at least one quarterly financial result for each company as of the execution date.

Where available, include one investor presentation.

Minimum target:
- 10 annual reports
- 10 quarterly results
- 5 investor presentations

Aim for at least 1,000 actual pages processed in total. If documents are unavailable or inaccessible, report this explicitly.

Do not fabricate documents, URLs, processing results or extracted values.

### 4. AGENT DELEGATION

Divide the work among specialized agents.

AGENT 1 — DOCUMENT RESEARCHER
- Find official company documents.
- Verify company names, financial periods and reporting basis.
- Download source PDFs.
- Maintain a document manifest.
- Record source URLs, download dates, file hashes and page counts.

AGENT 2 — OPEN-SOURCE TECHNOLOGY RESEARCHER
Evaluate these repositories:

- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- Docling: https://github.com/docling-project/docling
- MinerU: https://github.com/opendatalab/MinerU
- olmOCR: https://github.com/allenai/olmocr
- OCRmyPDF: https://github.com/ocrmypdf/OCRmyPDF
- Tesseract: https://github.com/tesseract-ocr/tesseract
- Unstructured: https://github.com/Unstructured-IO/unstructured

For each:
- Verify repository activity.
- Verify current installation requirements.
- Check licence of code and model weights separately.
- Identify GPU and RAM requirements.
- Test actual extraction quality.
- Record processing time and resource usage.
- Identify commercial deployment restrictions.

Do not assume every repository supports every format or that every model is commercially unrestricted.

AGENT 3 — OCR AND DOCUMENT PARSING ENGINEER
- Install the selected open-source tools.
- Build a unified processing interface.
- Implement PDF, image and Office document ingestion.
- Detect digital PDFs versus scanned PDFs.
- Route documents to appropriate parsers.
- Preserve page boundaries, tables, reading order and metadata.
- Generate Markdown and structured JSON.

AGENT 4 — DATA EXTRACTION ENGINEER
- Develop structured extraction schemas.
- Extract financial statements and company metadata.
- Extract management commentary and important events.
- Normalize currencies, units, dates and percentages.
- Preserve original extracted values.
- Produce JSON, CSV, Excel and Parquet datasets.

AGENT 5 — QUALITY ASSURANCE AND BENCHMARK ENGINEER
- Build a human-verified ground-truth dataset.
- Compare extracted outputs against original documents.
- Calculate OCR and table extraction metrics.
- Identify errors, missing values and incorrect numbers.
- Test duplicate detection and source traceability.
- Produce a ranked engine comparison.

AGENT 6 — FINANCIAL DATA ANALYST
For every company, extract:

INCOME STATEMENT:
- Revenue
- Operating income
- EBITDA, where reported or transparently calculated
- Depreciation and amortization
- EBIT
- Interest expense
- Profit before tax
- Profit after tax
- EPS

BALANCE SHEET:
- Total assets
- Total liabilities
- Equity
- Borrowings
- Cash and equivalents
- Investments
- Receivables
- Inventory

CASH FLOW:
- Operating cash flow
- Investing cash flow
- Financing cash flow
- Capital expenditure
- Free cash flow, with calculation methodology

ADDITIONAL INFORMATION:
- Segment revenue
- Segment profitability
- Management guidance
- Important business developments
- Risk disclosures
- Auditor observations
- Related-party transactions
- Subsidiaries and joint ventures

For banks, additionally extract:
- Net interest income
- Net interest margin
- Gross NPA
- Net NPA
- Provision coverage ratio
- Capital adequacy
- CASA ratio
- Deposits
- Advances

Do not force industrial-company financial metrics onto banks or vice versa.

### 5. TECHNICAL ARCHITECTURE

Build a self-hosted architecture using:

- Python
- FastAPI
- PyMuPDF
- Apache Tika
- PaddleOCR / PaddleOCR-VL
- Docling
- MinerU as an alternative parser
- Redis and Celery
- PostgreSQL
- MinIO
- Pydantic
- Pandera
- Polars
- PyArrow
- Docker Compose

Use local LLM inference where needed.

Prefer structured JSON outputs with schema validation.

No external paid OCR API should be mandatory.

### 6. REQUIRED PROCESSING WORKFLOW

For every document:

1. Download and preserve the original.
2. Calculate SHA-256.
3. Identify format and page count.
4. Determine whether pages contain digital text, scanned images or both.
5. Extract native content where possible.
6. Apply OCR where necessary.
7. Reconstruct tables.
8. Classify document sections.
9. Extract structured entities and financial values.
10. Normalize units, currency and reporting periods.
11. Validate arithmetic and data types.
12. Attach original source page and block references.
13. Store original, parsed and structured versions.
14. Export datasets.

Every extracted value must be traceable to its original source.

Never silently replace missing values with zero.

Never infer numerical values that cannot be verified.

Distinguish consolidated and standalone statements.

### 7. BENCHMARKING REQUIREMENTS

Run comparable tests on the same representative document pages.

Compare:
- PaddleOCR
- Docling
- MinerU
- olmOCR
- Tesseract where applicable

Measure:

1. Character Error Rate (CER)
2. Word Error Rate (WER)
3. Table extraction accuracy
4. Table structure similarity
5. Financial numerical exact-match accuracy
6. Entity extraction precision and recall
7. Reading-order accuracy
8. Processing time per page
9. Peak RAM and VRAM consumption
10. Failure and retry rate

Create a gold-standard dataset using human-verified source pages.

Target acceptance criteria:
- At least 99% OCR accuracy on clean scans.
- At least 95% OCR accuracy on difficult scans.
- At least 97% table cell accuracy.
- At least 99.5% financial numerical exact-match accuracy.
- 100% source-page traceability.

These are targets, not assumed results. Clearly report actual performance, including failures.

### 8. OUTPUT DATA STRUCTURE

Generate a unified schema.

Every extracted field should contain:

{
  "company": "",
  "document_type": "",
  "financial_year": "",
  "reporting_period": "",
  "reporting_basis": "",
  "field_name": "",
  "original_value": "",
  "normalized_value": null,
  "currency": null,
  "unit": null,
  "source_document": "",
  "source_page": null,
  "source_table": null,
  "source_text": "",
  "confidence": null,
  "validation_status": "",
  "extraction_engine": "",
  "model_version": ""
}

This is an illustrative contract. Adapt the schema where document types require additional fields.

### 9. REQUIRED DELIVERABLES

I want actual files and results, not just a written explanation.

Create:

A. EXECUTIVE REPORT
- What was processed.
- What worked.
- What failed.
- Best OCR engine.
- Best table extraction engine.
- Best overall parser.
- Performance and resource comparison.
- Recommended production architecture.

B. COMPANY DATASETS
One folder per company containing:
- Original documents or source manifest.
- Extracted Markdown.
- Structured JSON.
- Financial tables in CSV.
- Consolidated Excel workbook.
- Validation report.

C. BENCHMARK RESULTS
- OCR comparison CSV.
- Table extraction comparison CSV.
- Processing speed comparison.
- Resource utilization comparison.
- Accuracy scorecards.
- Failure analysis.

D. ENGINEERING OUTPUT
- Source code.
- Docker Compose.
- Python requirements and pinned dependencies.
- Configuration files.
- Database schemas.
- API documentation.
- README with installation and execution instructions.

E. MASTER DATASET
Create one consolidated dataset covering all 10 companies with consistent field names, reporting periods, currencies, units and source references.

### 10. RESULTS DASHBOARD

Produce a concise dashboard showing:

- Number of companies processed.
- Number of documents collected.
- Total pages processed.
- Successful extraction percentage.
- Average OCR accuracy.
- Financial numerical accuracy.
- Table extraction accuracy.
- Processing speed.
- Total processing time.
- Number of failed documents.
- Number of records requiring manual review.

Rank all tested engines based on actual benchmark results.

Include a company-by-company quality breakdown.

### 11. STRICT RULES

- Do not stop at research.
- Do not return only GitHub links.
- Do not fabricate benchmark scores.
- Do not use paid APIs without explicit approval.
- Do not hide failed documents.
- Do not confuse standalone and consolidated financial data.
- Do not discard footnotes.
- Do not lose the original source documents.
- Do not present LLM-generated interpretations as verified financial facts.
- Do not claim production readiness without load testing.
- Respect website terms, robots policies and document licences.
- Keep all sensitive processing local.
- If something cannot be completed, document the blocker and continue with the remaining work.

### 12. FINAL REPORT FORMAT

Present your final answer in this exact order:

1. Executive summary.
2. Ten companies and documents successfully collected.
3. OCR engines tested.
4. Benchmark results and rankings.
5. Company-wise extracted financial data.
6. Data quality and error analysis.
7. Best free open-source stack.
8. Hardware and performance requirements.
9. Production architecture recommendation.
10. Download links to all generated deliverables.

I want to review the results, compare the engines and make the final technology selection.

Your success is measured by the quality, completeness, accuracy and traceability of the actual extracted data — not by the length of your report.

**START EXECUTION.**