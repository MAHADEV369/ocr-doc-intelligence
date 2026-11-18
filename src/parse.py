"""Full-corpus parsing: native text, OCR fallback, tables, sections, markdown output."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import fitz

from . import config
from .ingest import iter_manifest, profile_document, render_page
from .quality import route_page

log = logging.getLogger("docintel.parse")

SECTION_RULES = [
    ("independent_auditor_report", [r"independent auditor'?s? report", r"auditor'?s? report"]),
    ("balance_sheet", [r"consolidated balance sheet", r"^balance sheet", r"consolidated profit and loss"]),
    ("profit_and_loss", [r"consolidated statement of profit and loss", r"statement of profit and loss",
                         r"consolidated profit and loss account", r"profit and loss account"]),
    ("cash_flow", [r"consolidated statement of cash flows?", r"statement of cash flows?", r"cash flow statement"]),
    ("notes_to_financial_statements", [r"notes (forming part of|to) the (consolidated )?financial statements",
                                       r"notes to accounts"]),
    ("management_discussion", [r"management discussion and analysis", r"md&a"]),
    ("boards_report", [r"board'?s report", r"directors'? report"]),
    ("corporate_governance", [r"corporate governance report", r"report on corporate governance"]),
    ("business_responsibility", [r"business responsibility and sustainability", r"brsr"]),
    ("segment_information", [r"segment (information|reporting)"]),
    ("related_party", [r"related party disclosures?"]),
    ("risk_management", [r"risk management"]),
    ("five_year_summary", [r"five year (financial )?(highlights|summary)", r"ten year (financial )?highlights"]),
    ("shareholder_information", [r"shareholder information", r"general shareholder information"]),
    ("directors_report", [r"report of the directors"]),
]

HEADING_RE = re.compile(r"^[A-Z][A-Za-z&’' ,\-()/]{4,90}$")


def classify_page(text: str, prev_section: str = "front_matter") -> tuple[str, bool]:
    """Return (section, is_heading_page). Uses the first 12 non-empty lines."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()][:14]
    head = " ".join(lines).lower()
    is_heading = False
    for line in lines[:6]:
        if HEADING_RE.match(line) and len(line.split()) <= 10:
            is_heading = True
            break
    for name, pats in SECTION_RULES:
        for pat in pats:
            if re.search(pat, head, re.I):
                # notes are only a section if they appear as a heading, not a cross-reference
                if name == "notes_to_financial_statements" and not re.search(r"notes (forming|to)", " ".join(lines[:3]).lower()):
                    continue
                return name, is_heading
    if prev_section in ("balance_sheet", "profit_and_loss", "cash_flow", "notes_to_financial_statements") and len(text) > 500:
        return prev_section, is_heading
    return prev_section if prev_section != "front_matter" else "front_matter", is_heading


NUM_TOKEN = re.compile(r"^\(?-?(?:[\d,]+(?:\.\d+)?|\.\d+)\)?$|^\(?-?[\d,]+(?:\.\d+)?%?\)?$")


def _clean_num(s: str):
    s = s.strip().replace("`", "").replace("₹", "").replace("$", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("%", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def page_tables(page: fitz.Page) -> list[list[list[str]]]:
    try:
        tabs = page.find_tables().tables
    except Exception:
        return []
    out = []
    for t in tabs:
        try:
            grid = [[str(c or "").strip() for c in row] for row in t.extract()]
        except Exception:
            continue
        if len(grid) >= 2 and max(len(r) for r in grid) >= 2:
            out.append(grid)
    return out


def ocr_page_tesseract(image: Path, psm: int = 3) -> tuple[str, float, float]:
    """Return (text, seconds, mean confidence)."""
    import pytesseract
    from PIL import Image
    from pytesseract import Output
    t = time.perf_counter()
    data = pytesseract.image_to_data(
        Image.open(image), lang="eng", output_type=Output.DICT,
        config=f"--oem 1 --psm {psm} --dpi {config.OCR_DPI}",
    )
    lines: dict[tuple[int, int, int], list[str]] = {}
    confs: list[float] = []
    for i, text in enumerate(data.get("text", [])):
        text = (text or "").strip()
        if text:
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(text)
        try:
            c = float(data["conf"][i])
            if c >= 0:
                confs.append(c)
        except Exception:
            pass
    txt = "\n".join(" ".join(parts) for _, parts in sorted(lines.items()))
    confidence = round(sum(confs) / len(confs), 2) if confs else 0.0
    return txt, time.perf_counter() - t, confidence


def process_document(slug: str, doc_type: str, path: Path, ocr_scanned: bool = True,
                     max_pages: int | None = None) -> dict:
    t0 = time.perf_counter()
    doc = fitz.open(path)
    prof = profile_document(path, doc=doc)
    page_limit = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
    out_dir = config.PARSED / slug / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_jsonl = out_dir / "pages.jsonl"
    md_path = out_dir / "document.md"
    ocr_pages = []
    section = "front_matter"
    warnings: list[str] = []
    md_parts = [f"# {slug} — {doc_type}\n\nSource: `{path}` · SHA-256 `{prof.sha256}` · {prof.pages} pages\n"]
    page_records = []
    with open(pages_jsonl, "w") as fj:
        for i in range(page_limit):
            page = doc[i]
            try:
                native = page.get_text("text", sort=True)
                profile = prof.page_profiles[i]
                route = profile.route or route_page(page)[0]
                route_reason = profile.route_reason
                quality = profile.quality_score
                kind = profile.kind
                used_ocr = False
                ocr_confidence = None
                if ocr_scanned and route == "scanned":
                    img = render_page(path, i + 1, config.PAGES / slug / doc_type, dpi=config.OCR_DPI, doc=doc)
                    # PSMs: 6 for table-like pages, 3 for narrative pages.
                    try:
                        has_tables_hint = bool(page.find_tables().tables)
                    except Exception:
                        has_tables_hint = False
                    psm = 6 if has_tables_hint else 3
                    native, secs, ocr_confidence = ocr_page_tesseract(img, psm=psm)
                    used_ocr = True
                    ocr_pages.append({"page": i + 1, "seconds": round(secs, 3),
                                      "engine": "tesseract", "confidence": ocr_confidence})
                section, is_heading = classify_page(native, section)
                tables = page_tables(page) if route == "digital" and len(native) > 40 else []
                md_parts.append(f"\n<!-- page: {i+1} label: {page.get_label() or ''} "
                                f"route: {route} engine: {'tesseract' if used_ocr else 'pymupdf'} -->\n\n{native.strip()}\n")
                for ti, grid in enumerate(tables):
                    md_parts.append(f"\n**Table {i+1}.{ti+1}**\n\n")
                    if grid:
                        width = max(len(r) for r in grid)
                        rows = [r + [""] * (width - len(r)) for r in grid]
                        md_parts.append("| " + " | ".join(rows[0]) + " |\n")
                        md_parts.append("|" + "---|" * width + "\n")
                        for r in rows[1:]:
                            md_parts.append("| " + " | ".join(r) + " |\n")
                rec = {
                    "page": i + 1, "page_label": page.get_label() or "", "chars": len(native),
                    "kind": kind, "route": route, "route_reason": route_reason,
                    "quality_score": quality, "section": section,
                    "section_start": is_heading, "ocr": used_ocr,
                    "ocr_confidence": ocr_confidence, "tables": len(tables),
                    "warnings": [],
                }
                page_records.append(rec)
                fj.write(json.dumps({"page": i + 1, "page_label": rec["page_label"],
                                     "text": native, "section": section, "route": route,
                                     "quality_score": quality, "tables": tables, "ocr": used_ocr,
                                     "ocr_confidence": ocr_confidence}) + "\n")
            except Exception as exc:
                msg = f"page {i+1}: {type(exc).__name__}: {exc}"
                warnings.append(msg)
                log.warning("%s %s %s", slug, doc_type, msg)
                fj.write(json.dumps({"page": i + 1, "text": "", "section": section,
                                     "tables": [], "ocr": False, "error": msg}) + "\n")
                page_records.append({"page": i + 1, "section": section, "error": msg})
    md_path.write_text("".join(md_parts))
    profile_path = out_dir / "profile.json"
    profile_path.write_text(prof.model_dump_json(indent=1))
    meta = {
        "slug": slug, "doc_type": doc_type, "file": str(path), "sha256": prof.sha256,
        "pages": prof.pages, "processed_pages": page_limit,
        "digital_pages": prof.digital_pages, "scanned_pages": prof.scanned_pages,
        "mixed_pages": prof.mixed_pages, "ocr_pages": ocr_pages,
        "processing_seconds": round(time.perf_counter() - t0, 2),
        "engine": "PyMuPDF native + Tesseract OCR fallback", "ocr_dpi": config.OCR_DPI,
        "markdown": str(md_path), "pages_jsonl": str(pages_jsonl),
        "sections": sorted({r.get("section") for r in page_records if r.get("section")}),
        "warnings": warnings,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    doc.close()
    return meta


def process_all(ocr_scanned: bool = True):
    metas = []
    for manifest, d, path in iter_manifest():
        meta = process_document(manifest["slug"], d["doc_type"], path, ocr_scanned=ocr_scanned)
        metas.append(meta)
        print(f"{manifest['slug']:12s} {d['doc_type']:22s} {meta['pages']:4d} pages  "
              f"{meta['processing_seconds']:6.1f}s  ocr={len(meta['ocr_pages'])}")
    out = config.STRUCTURED / "parse_meta.json"
    out.write_text(json.dumps(metas, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    process_all()
