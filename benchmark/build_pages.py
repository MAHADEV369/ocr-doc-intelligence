"""Build benchmark page assets (PNG + single-page PDF + native gold text/tables)."""
from __future__ import annotations

import json
from pathlib import Path

import fitz

from src import config
from src.ingest import render_page

BENCH = config.BENCHMARK


def build():
    pages = json.loads((BENCH / "pages.json").read_text())
    # add a Reliance narrative page (two-up annual report layout; chosen manually)
    if not any(p["slug"] == "reliance" and p["kind"] == "narrative" for p in pages):
        pages.append({"slug": "reliance", "kind": "narrative", "page": 20,
                      "pdf": str(config.RAW / "reliance" / "annual_report_fy2026.pdf")})
    records = []
    for p in pages:
        pdf = Path(p["pdf"])
        out = BENCH / "pages" / f"{p['slug']}_{p['kind']}"
        out.mkdir(parents=True, exist_ok=True)
        img = render_page(pdf, p["page"], out)
        spdf = out / f"p{p['page']:04d}.pdf"
        spdf.unlink(missing_ok=True)
        if True:
            pix = fitz.open(pdf)[p["page"] - 1].get_pixmap(dpi=config.RENDER_DPI, colorspace=fitz.csRGB, alpha=False)
            new = fitz.open()
            pg = new.new_page(width=pix.width * 72 / config.RENDER_DPI,
                              height=pix.height * 72 / config.RENDER_DPI)
            pg.insert_image(pg.rect, filename=str(img))
            new.save(spdf)
            new.close()
        doc = fitz.open(pdf)
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
        records.append({**p, "image": str(img), "single_page_pdf": str(spdf),
                        "gold_chars": len(text), "tables": len(tables)})
        print(p["slug"], p["kind"], p["page"], len(text), len(tables))
    (BENCH / "manifest.json").write_text(json.dumps(records, indent=1))
    print("pages", len(records))


if __name__ == "__main__":
    build()
