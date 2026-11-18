"""Build a 100-page stratified benchmark set from the ten annual reports.

The set is larger than the original 20-page benchmark and includes statement
pages, dense table/notes pages and narrative pages. Gold text remains the
publisher's native layer, so it measures OCR fidelity rather than human
annotation.
"""
from __future__ import annotations

import json
import re

import fitz

from src import config
from src.ingest import render_page
from src.statements import STATEMENT_PAGES

BENCH = config.BENCHMARK
OUT = BENCH / "pages_extended"
PER_COMPANY = 10


def _score_narrative(text: str) -> tuple[int, int]:
    digits = len(re.findall(r"\d", text))
    ratio = digits / max(1, len(text))
    return (0 if 900 <= len(text) <= 5000 and ratio < 0.12 else 1, abs(len(text) - 2200))


def select() -> list[dict]:
    selected: list[dict] = []
    for c in config.COMPANIES:
        slug = c["slug"]
        pdf = config.RAW / slug / "annual_report_fy2026.pdf"
        doc = fitz.open(pdf)
        picked: list[dict] = []
        seen: set[int] = set()
        seeds = STATEMENT_PAGES.get(slug, {})
        for section in ("balance_sheet", "profit_and_loss"):
            for page_no in (seeds.get(section) or [])[:1]:
                if page_no not in seen and 1 <= page_no <= doc.page_count:
                    picked.append({"slug": slug, "kind": "financial_table", "page": page_no,
                                   "pdf": str(pdf)})
                    seen.add(page_no)
        # Dense pages with tables, then narrative pages.
        table_candidates, narrative_candidates = [], []
        for i in range(doc.page_count):
            text = doc[i].get_text("text")
            if len(text.strip()) < 250:
                continue
            try:
                ntab = len(doc[i].find_tables().tables)
            except Exception:
                ntab = 0
            if ntab:
                table_candidates.append((i + 1, -ntab, len(text)))
            else:
                narrative_candidates.append((i + 1, *_score_narrative(text)))
        for page_no, _, _ in sorted(table_candidates)[:2]:
            if page_no not in seen:
                picked.append({"slug": slug, "kind": "notes_table", "page": page_no,
                               "pdf": str(pdf)})
                seen.add(page_no)
        for page_no, _, _ in sorted(narrative_candidates, key=lambda x: (x[1], x[2]))[:6]:
            if page_no not in seen and len(picked) < PER_COMPANY:
                picked.append({"slug": slug, "kind": "narrative", "page": page_no,
                               "pdf": str(pdf)})
                seen.add(page_no)
        # Fill any gap from the remaining text pages.
        if len(picked) < PER_COMPANY:
            for i in range(doc.page_count):
                if len(picked) >= PER_COMPANY:
                    break
                if i + 1 in seen or len(doc[i].get_text("text").strip()) < 200:
                    continue
                picked.append({"slug": slug, "kind": "narrative", "page": i + 1,
                               "pdf": str(pdf)})
                seen.add(i + 1)
        selected.extend(picked[:PER_COMPANY])
        doc.close()
        print(slug, len(picked[:PER_COMPANY]))
    return selected


def build():
    pages = select()
    (BENCH / "pages_extended.json").write_text(json.dumps(pages, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for p in pages:
        key = f"{p['slug']}_{p['kind']}_p{p['page']}"
        out = OUT / key
        out.mkdir(parents=True, exist_ok=True)
        img = render_page(p["pdf"], p["page"], out)
        spdf = out / f"p{p['page']:04d}.pdf"
        spdf.unlink(missing_ok=True)
        pix = fitz.open(p["pdf"])[p["page"] - 1].get_pixmap(
            dpi=config.RENDER_DPI, colorspace=fitz.csRGB, alpha=False)
        new = fitz.open()
        pg = new.new_page(width=pix.width * 72 / config.RENDER_DPI,
                          height=pix.height * 72 / config.RENDER_DPI)
        pg.insert_image(pg.rect, filename=str(img))
        new.save(spdf)
        new.close()
        doc = fitz.open(p["pdf"])
        page = doc[p["page"] - 1]
        text = page.get_text("text")
        tables = []
        try:
            for t in page.find_tables().tables:
                tables.append([[str(c or "").strip() for c in row] for row in t.extract()])
        except Exception:
            pass
        (out / "gold.txt").write_text(text)
        (out / "gold_tables.json").write_text(json.dumps(tables, indent=1))
        records.append({**p, "key": key, "image": str(img), "single_page_pdf": str(spdf),
                        "gold_chars": len(text), "tables": len(tables)})
        doc.close()
    (BENCH / "manifest_extended.json").write_text(json.dumps(records, indent=1))
    print("pages", len(records))


if __name__ == "__main__":
    build()
