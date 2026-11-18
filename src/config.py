"""Central configuration for the Indian corporate document intelligence pipeline."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
MANIFESTS = DATA / "manifests"
PAGES = DATA / "pages"
PARSED = DATA / "parsed"
STRUCTURED = DATA / "structured"
BENCHMARK = DATA / "benchmark"
GROUND_TRUTH = DATA / "ground_truth"
COMPANY_DATASETS = ROOT / "company_datasets"
REPORTS = ROOT / "reports"
DELIVERABLES = ROOT / "deliverables"
LOGS = ROOT / "logs"

for _p in (RAW, MANIFESTS, PAGES, PARSED, STRUCTURED, BENCHMARK,
           GROUND_TRUTH, COMPANY_DATASETS, REPORTS, DELIVERABLES, LOGS):
    _p.mkdir(parents=True, exist_ok=True)

# Rendering
RENDER_DPI = int(os.getenv("OCR_RENDER_DPI", "200"))
OCR_DPI = int(os.getenv("OCR_DPI", "300"))
# A page is considered digital if it has at least this many native characters.
DIGITAL_TEXT_MIN_CHARS = int(os.getenv("DIGITAL_TEXT_MIN_CHARS", "120"))

# Extraction
CANONICAL_UNIT = "INR crore"
RUN_ID = os.getenv("DOCINTEL_RUN_ID") or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
TESSERACT_CONFIDENCE_MIN = float(os.getenv("TESSERACT_CONFIDENCE_MIN", "72"))
# API safety
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
API_TOKEN = os.getenv("DOCINTEL_API_TOKEN", "")
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]

ENGINES = ["native", "tesseract", "paddleocr", "docling", "mineru", "ocrmypdf", "olmocr"]

COMPANIES = [
    {"slug": "reliance", "name": "Reliance Industries Limited", "sector": "Conglomerate", "kind": "industrial"},
    {"slug": "hdfc", "name": "HDFC Bank Limited", "sector": "Banking", "kind": "bank"},
    {"slug": "tcs", "name": "Tata Consultancy Services Limited", "sector": "IT Services", "kind": "industrial"},
    {"slug": "icici", "name": "ICICI Bank Limited", "sector": "Banking", "kind": "bank"},
    {"slug": "infosys", "name": "Infosys Limited", "sector": "IT Services", "kind": "industrial"},
    {"slug": "larsen", "name": "Larsen & Toubro Limited", "sector": "Engineering & Construction", "kind": "industrial"},
    {"slug": "itc", "name": "ITC Limited", "sector": "FMCG", "kind": "industrial"},
    {"slug": "tatamotors", "name": "Tata Motors Limited", "sector": "Automotive", "kind": "industrial"},
    {"slug": "sunpharma", "name": "Sun Pharmaceutical Industries Limited", "sector": "Pharmaceuticals", "kind": "industrial"},
    {"slug": "airtel", "name": "Bharti Airtel Limited", "sector": "Telecom", "kind": "industrial"},
]
COMPANY_BY_SLUG = {c["slug"]: c for c in COMPANIES}
BANK_SLUGS = {c["slug"] for c in COMPANIES if c["kind"] == "bank"}
