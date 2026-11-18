"""End-to-end orchestration: ingest -> route -> parse -> extract -> validate -> export.

Parser selection:
    DOCINTEL_PARSER=hybrid   (default) PyMuPDF + Tesseract/Paddle + Docling
    DOCINTEL_PARSER=native   PyMuPDF + Tesseract only (legacy path)
"""
from __future__ import annotations

import argparse
import json
import os

from . import config, store
from .export import export_all
from .parse import process_document
from .production_extractor import HybridExtractor
from .quarterly import extract_quarter
from .statements import extract_annual


def _parse_one(slug: str, doc_type: str, path, parser: str, max_pages: int | None) -> dict:
    if parser == "hybrid":
        out_dir = config.PARSED / slug / doc_type
        ex = HybridExtractor(dpi=config.OCR_DPI)
        result = ex.extract(path, out_dir=out_dir, max_pages=max_pages)
        return ex.write_parsed(result, out_dir, slug, doc_type)
    return process_document(slug, doc_type, path, max_pages=max_pages)


def run(slug: str | None = None, parser: str | None = None,
        max_pages: int | None = None, sync_store: bool = True):
    parser = parser or os.getenv("DOCINTEL_PARSER", "hybrid")
    if parser not in ("hybrid", "native"):
        raise ValueError("parser must be 'hybrid' or 'native'")
    for manifest in sorted(config.MANIFESTS.glob("*.json")):
        m = json.loads(manifest.read_text())
        if slug and m["slug"] != slug:
            continue
        print(f"== {m['company']} ({m['slug']})")
        for d in m["documents"]:
            if d.get("status", "downloaded") != "downloaded":
                continue
            p = config.ROOT / d["file"]
            if not p.exists():
                print("  missing file", p)
                continue
            meta = _parse_one(m["slug"], d["doc_type"], p, parser, max_pages)
            print(f"  parsed {d['doc_type']} [{parser}]: "
                  f"{meta.get('processed_pages', meta.get('pages', 0))} pages, "
                  f"{meta.get('processing_seconds', 0)}s")
            if d["doc_type"] == "annual_report":
                fields = extract_annual(m["slug"], p)
            elif d["doc_type"] == "quarterly_results":
                fields = extract_quarter(m["slug"], p)
            else:
                fields = []
            print(f"  extracted {len(fields)} fields")
    export_all()
    if sync_store and store.enabled():
        print("syncing to", "postgres/minio" if store.S3_ENDPOINT else "postgres")
        print(store.sync_all())


def main():
    ap = argparse.ArgumentParser(description="Run the document-intelligence pipeline")
    ap.add_argument("slug", nargs="?", help="one company slug (default: all)")
    ap.add_argument("--parser", choices=["hybrid", "native"],
                    default=os.getenv("DOCINTEL_PARSER", "hybrid"))
    ap.add_argument("--max-pages", type=int, default=None,
                    help="process only the first N pages per document (smoke tests)")
    ap.add_argument("--no-store", action="store_true", help="skip Postgres/MinIO sync")
    args = ap.parse_args()
    run(args.slug, args.parser, args.max_pages, sync_store=not args.no_store)


if __name__ == "__main__":
    main()
