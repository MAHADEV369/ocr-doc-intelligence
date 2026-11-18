# Open-source engine research (verified 14 Nov 2026)

Stars, last-push dates and licences were read from the GitHub REST API on the execution date. Model
weight licences were read from the Hugging Face model cards. Installation was tested on the host
described in `reports/hardware.md`.

| Repository | Stars | Last push | Code licence | Model-weight licence | Commercial restriction |
|---|---:|---|---|---|---|
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | 92,681 | 2026-09-16 | Apache-2.0 | PP-OCRv6 / PaddleOCR-VL: Apache-2.0 | None |
| [Docling](https://github.com/docling-project/docling) | 70,558 | 2026-11-13 | MIT | layout/TableFormer Apache-2.0; CodeFormula CDLA-Permissive-2.0 | None |
| [MinerU](https://github.com/opendatalab/MinerU) | 83,636 | 2026-11-13 | Apache-2.0 **plus additional terms** | PDF-Extract-Kit-1.0: AGPL-3.0 | Commercial licence required above stated revenue/user thresholds; AGPL weights need legal review |
| [olmOCR](https://github.com/allenai/olmocr) | 19,822 | 2026-03-25 | Apache-2.0 | olmOCR-2-7B-1025: Apache-2.0 | Requires CUDA/vLLM; no macOS support |
| [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) | 35,310 | 2026-11-09 | MPL-2.0 | Tesseract/tessdata Apache-2.0 | File-level copyleft on MPL files |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | 77,502 | 2026-11-13 | Apache-2.0 | eng traineddata Apache-2.0 | None |
| [Unstructured](https://github.com/Unstructured-IO/unstructured) | 15,733 | 2026-11-14 | Apache-2.0 | core permissive; optional model bundles vary | Hosted platform is paid; not a standalone OCR engine |

## Installation and hardware

| Engine | Install used here | Model download | RAM / GPU |
|---|---|---|---|
| Tesseract 5.5.4 | `brew install tesseract` | 4 MB eng data | ~160 MB CPU |
| PaddleOCR 3.7.0 | `pip install paddlepaddle==3.3.1 paddleocr==3.7.0` | ~200 MB PP-OCRv6 | 6.8 GB peak CPU; GPU optional |
| Docling 2.150.0 | `pip install docling==2.150.0` | layout + TableFormer (few hundred MB) | CPU/MPS; warm page seconds |
| MinerU 3.0.9 | `pip install mineru==3.0.9` | ~1.1 GB PDF-Extract-Kit | CPU pipeline works; GPU recommended |
| OCRmyPDF 17.14.1 | `pip install ocrmypdf` + Ghostscript | uses Tesseract | ~60 MB CPU |
| olmOCR 0.4.27 | `pip install olmocr==0.4.27` | ~15 GB 7B model | Needs CUDA GPU; **blocked here** |
| Unstructured | `pip install unstructured[pdf]` | optional hi_res models | Not ranked; delegates OCR |

## What could not be tested and why

- **olmOCR**: the reference pipeline imports vLLM, which has no macOS/MPS backend. A 7B model also
  exceeds the comfortable memory budget of a 16 GB unified-memory host. Excluded from the numeric
  ranking; licence research completed.
- **Unstructured**: its open-source core is a partitioning/orchestration library. `hi_res` pulls a
  heavy detectron2/ONNX stack and delegates OCR to Tesseract/PaddleOCR, so a separate OCR quality
  number would duplicate those engines. Documented as an architecture component, not ranked.
- **OCRmyPDF**: passed 20/20 image-only benchmark pages; its accuracy is close to Tesseract because
  Tesseract is the OCR core. On the original signed PDFs it refuses to modify digitally signed files
  (observed during the first run) and some repaired outputs were rejected, so production should strip
  signatures or OCR a rendered copy.
