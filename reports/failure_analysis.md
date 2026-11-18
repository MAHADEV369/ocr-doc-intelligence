# Failure analysis

Total engine-page failures recorded: **0** of 100 engine-page runs.

- tesseract: 0 failures
- ocrmypdf: 0 failures
- paddleocr: 0 failures
- docling: 0 failures
- mineru: 0 failures

## Failure detail

| Engine | Company | Page | Error |
|---|---|---:|---|

## Non-run engines

- **olmOCR 0.4.27**: blocked, requires CUDA/vLLM; no macOS backend. Model weights are Apache-2.0.
- **Unstructured**: not a standalone OCR engine; hi_res delegates OCR and its model stack was not installed.

## Measurement notes

- Empty output is counted as a failure, not a successful run.
- Memory is measured for the engine process and any child process (MinerU/OCRmyPDF run in subprocesses).
- Runtime warnings are captured in the per-run logs; they are not silently discarded.
