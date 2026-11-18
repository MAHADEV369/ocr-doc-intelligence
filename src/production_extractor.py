"""Production-grade hybrid extractor.

Routing
-------
digital page  -> PyMuPDF native text; PyMuPDF tables; Docling table structure on
                 statement pages (no OCR of the text layer).
scanned page  -> 300 DPI render, deskew/denoise, PaddleOCR text, Docling table
                 structure, cell-level fusion (Docling grid + PaddleOCR digits),
                 arithmetic cross-foot checks.

Output: JSON + Markdown + per-table CSV, with page-level provenance and the
engine used for each page/table. No value is silently replaced with zero.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from PIL import Image, ImageOps

from . import config
from .quality import items_to_text, order_items, route_page

log = logging.getLogger("docintel.extract")

STATEMENT_HINTS = re.compile(
    r"balance sheet|statement of profit|profit and loss|cash flow|financial results|"
    r"statement of assets|income statement|segment revenue", re.I)
NUM_RE = re.compile(r"^\(?-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)\)?$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _num(s: str) -> float | None:
    s = s.strip().replace("₹", "").replace("`", "").replace("O", "0").replace("o", "0")
    if s in {"-", "–", "—", ""}:
        return 0.0 if s else None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("%", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    v = float(s)
    return -v if neg else v


def _cell_text(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


@dataclass
class TableResult:
    grid: list[list[str]]
    engine: str
    bbox: list[float] | None = None
    checks: list[dict] = field(default_factory=list)
    status: str = "unverified"
    html: str = ""


@dataclass
class PageResult:
    page: int
    route: str
    text: str
    engine: str
    tables: list[TableResult] = field(default_factory=list)
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    route_reason: str = ""
    quality_score: float = 0.0
    ocr_confidence: float | None = None

    def to_dict(self):
        return {
            "page": self.page, "route": self.route, "route_reason": self.route_reason,
            "quality_score": self.quality_score, "engine": self.engine,
            "ocr_confidence": self.ocr_confidence,
            "text": self.text, "seconds": round(self.seconds, 3),
            "warnings": self.warnings,
            "tables": [
                {"engine": t.engine, "bbox": t.bbox, "status": t.status,
                 "checks": t.checks, "grid": t.grid, "html": t.html} for t in self.tables
            ],
        }


class HybridExtractor:
    def __init__(self, dpi: int = 300, deskew: bool = True, force_ocr: bool = False,
                 docling_statements: bool = True, ocr_engine: str = "auto",
                 tesseract_confidence_min: float | None = None):
        self.dpi = dpi
        self.deskew = deskew
        self.force_ocr = force_ocr
        self.docling_statements = docling_statements
        self.ocr_engine = ocr_engine  # auto | tesseract | paddle
        self.tesseract_confidence_min = (
            config.TESSERACT_CONFIDENCE_MIN if tesseract_confidence_min is None
            else tesseract_confidence_min
        )
        self._paddle = None
        self._docling = None
        self._last_route: tuple[str, str, float] = ("digital", "", 0.0)

    # ---------- lazy models ----------
    @property
    def paddle(self):
        if self._paddle is None:
            from paddleocr import PaddleOCR
            log.info("loading PaddleOCR PP-OCRv6")
            self._paddle = PaddleOCR(use_doc_orientation_classify=True,
                                     use_doc_unwarping=True,
                                     use_textline_orientation=True, lang="en")
        return self._paddle

    @property
    def docling(self):
        if self._docling is None:
            from docling.document_converter import DocumentConverter
            log.info("loading Docling layout + TableFormer")
            self._docling = DocumentConverter()
        return self._docling

    # ---------- page routing ----------
    def _page_text(self, page: fitz.Page) -> str:
        return page.get_text("text")

    def _route_details(self, page: fitz.Page) -> tuple[str, str, float]:
        route, reason, score = route_page(page, force_ocr=self.force_ocr)
        self._last_route = (route, reason, score)
        return route, reason, score

    def _route(self, page: fitz.Page) -> str:
        return self._route_details(page)[0]

    # ---------- image prep ----------
    def _render(self, page: fitz.Page, out_dir: Path) -> tuple[Path, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        img_path = out_dir / f"p{page.number+1:04d}.png"
        pdf_path = out_dir / f"p{page.number+1:04d}.pdf"
        pix = page.get_pixmap(dpi=self.dpi, colorspace=fitz.csRGB, alpha=False)
        pix.save(img_path)
        if not pdf_path.exists():
            new = fitz.open()
            pg = new.new_page(width=pix.width * 72 / self.dpi, height=pix.height * 72 / self.dpi)
            pg.insert_image(pg.rect, filename=str(img_path))
            new.save(pdf_path); new.close()
        return img_path, pdf_path

    def _page_pdf(self, page: fitz.Page, out_dir: Path) -> Path:
        """Single-page vector PDF when possible (preserves the native text layer)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"p{page.number+1:04d}_vector.pdf"
        if out.exists():
            return out
        try:
            new = fitz.open()
            new.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
            new.save(out)
            new.close()
            return out
        except Exception:
            img, spdf = self._render(page, out_dir)
            return spdf

    def _preprocess(self, image_path: Path) -> Path:
        out = image_path.with_name(image_path.stem + "_pre.png")
        img = Image.open(image_path).convert("L")
        img = ImageOps.autocontrast(img)
        try:
            import cv2
            arr = np.asarray(img)
            # CLAHE makes faint scanned digits easier to recognise without
            # destroying the light table rules.
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            arr = clahe.apply(arr)
            if self.deskew:
                thr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
                # Remove long table rules before estimating the text angle.
                h, w = thr.shape
                horiz = cv2.morphologyEx(thr, cv2.MORPH_OPEN,
                                         cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 20), 1)))
                vert = cv2.morphologyEx(thr, cv2.MORPH_OPEN,
                                        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 20))))
                text_mask = cv2.subtract(thr, cv2.bitwise_or(horiz, vert))
                coords = np.column_stack(np.where(text_mask > 0))
                if len(coords) > 100:
                    angle = cv2.minAreaRect(coords)[-1]
                    angle = -(90 + angle) if angle < -45 else -angle
                    if 0.2 < abs(angle) < 8:
                        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                        arr = cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_CUBIC,
                                             borderMode=cv2.BORDER_REPLICATE)
            img = Image.fromarray(arr)
        except Exception as e:
            log.warning("preprocess failed: %s", e)
        img.convert("RGB").save(out)
        return out

    # ---------- OCR ----------
    def _tesseract_page(self, image_path: Path, page_w: float, page_h: float):
        """Return (text, items, mean_confidence) using Tesseract word boxes."""
        import pytesseract
        from pytesseract import Output
        data = pytesseract.image_to_data(
            Image.open(image_path), lang="eng", output_type=Output.DICT,
            config=f"--oem 1 --psm 3 --dpi {self.dpi}",
        )
        w, h = Image.open(image_path).size
        items, confs = [], []
        lines: dict[tuple[int, int, int], list[str]] = {}
        for i, text in enumerate(data.get("text", [])):
            text = (text or "").strip()
            if not text:
                continue
            try:
                score = float(data["conf"][i]) / 100.0
            except Exception:
                score = 0.0
            if score < 0:
                score = 0.0
            x, y = float(data["left"][i]), float(data["top"][i])
            bw, bh = float(data["width"][i]), float(data["height"][i])
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(text)
            items.append({
                "text": text, "score": score,
                "bbox": [x * page_w / w, y * page_h / h,
                         (x + bw) * page_w / w, (y + bh) * page_h / h],
                "line": key,
            })
            if score > 0:
                confs.append(score)
        # Tesseract already gives a usable reading order through block/line
        # keys; do not re-sort its table rows with a column cut.
        text = "\n".join(" ".join(parts) for _, parts in sorted(lines.items()))
        confidence = round(100 * sum(confs) / len(confs), 2) if confs else 0.0
        return text, items, confidence

    def _paddle_page(self, image_path: Path, page_w: float, page_h: float):
        res = self.paddle.predict(str(image_path))[0]
        w, h = Image.open(image_path).size
        items = []
        for i, text in enumerate(res["rec_texts"]):
            if not text.strip():
                continue
            poly = res["rec_polys"][i] if i < len(res["rec_polys"]) else None
            score = float(res["rec_scores"][i]) if i < len(res["rec_scores"]) else 0.0
            if poly is None:
                continue
            pts = np.asarray(poly, dtype=float)
            x0, y0 = pts[:, 0].min(), pts[:, 1].min()
            x1, y1 = pts[:, 0].max(), pts[:, 1].max()
            items.append({
                "text": text, "score": score,
                "bbox": [x0 * page_w / w, y0 * page_h / h, x1 * page_w / w, y1 * page_h / h],
            })
        items = order_items(items, page_w)
        text = items_to_text(items, page_w)
        return text, items

    # ---------- Docling tables ----------
    def _docling_tables(self, pdf_path: Path, page_no: int):
        try:
            res = self.docling.convert(str(pdf_path))
        except Exception as e:
            log.warning("Docling failed on %s: %s", pdf_path, e)
            return []
        doc = res.document
        out = []
        for tab in getattr(doc, "tables", []):
            try:
                grid_cells = tab.data.grid
            except Exception:
                continue
            grid, bboxes = [], []
            for row in grid_cells:
                r, rb = [], []
                for cell in row:
                    r.append(_cell_text(cell.text))
                    bb = cell.bbox
                    rb.append([bb.l, bb.t, bb.r, bb.b] if bb else None)
                grid.append(r); bboxes.append(rb)
            if not grid:
                continue
            out.append({"grid": grid, "bboxes": bboxes})
        return out

    @staticmethod
    def _nums(text: str) -> list[float]:
        out = []
        for tok in re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", text or ""):
            v = _num(tok)
            if v is not None:
                out.append(v)
        return out

    def _fuse_table(self, table: dict, ocr_items: list[dict]) -> list[list[str]]:
        """Use Docling for structure and OCR for cell text only when they agree.

        Length is a bad tie-breaker: a longer OCR string can be a merge of two
        cells or a hallucinated suffix. Prefer numeric agreement, then string
        similarity, then the higher-confidence OCR text.
        """
        grid = [row[:] for row in table["grid"]]
        bboxes = table.get("bboxes") or []
        for ri, row in enumerate(grid):
            for ci, cell in enumerate(row):
                bb = bboxes[ri][ci] if ri < len(bboxes) and ci < len(bboxes[ri]) else None
                if not bb:
                    continue
                x0, y0, x1, y1 = bb
                inside = [it for it in ocr_items
                          if x0 <= (it["bbox"][0] + it["bbox"][2]) / 2 <= x1
                          and y0 <= (it["bbox"][1] + it["bbox"][3]) / 2 <= y1]
                if not inside:
                    continue
                merged = " ".join(it["text"] for it in inside).strip()
                if not merged:
                    continue
                docling_nums = self._nums(cell)
                ocr_nums = self._nums(merged)
                # If both are numeric, only replace when the numbers agree.
                if docling_nums and ocr_nums:
                    if len(docling_nums) == len(ocr_nums) and all(
                            abs(a - b) <= max(0.01, abs(a) * 1e-6)
                            for a, b in zip(docling_nums, ocr_nums)):
                        grid[ri][ci] = merged
                    continue
                if not cell.strip() and merged:
                    grid[ri][ci] = merged
                    continue
                if not docling_nums and ocr_nums:
                    # OCR often recovers a number Docling dropped.
                    grid[ri][ci] = merged
                    continue
                # Non-numeric text: use similarity and OCR confidence.
                ratio = difflib.SequenceMatcher(None, cell.lower(), merged.lower()).ratio()
                avg_conf = sum(it.get("score", 0.0) for it in inside) / len(inside)
                if ratio >= 0.62 and avg_conf >= 0.55:
                    grid[ri][ci] = merged
        return grid

    # ---------- table validation ----------
    def _validate_table(self, grid: list[list[str]]) -> tuple[list[dict], str]:
        checks = []
        if not grid:
            return checks, "unverified"
        width = max(len(r) for r in grid)
        rows = [r + [""] * (width - len(r)) for r in grid]
        total_idx = None
        for i, r in enumerate(rows):
            if re.search(r"\b(total|grand total)\b", _cell_text(r[0]).lower()):
                total_idx = i
        end = total_idx if total_idx is not None else len(rows)
        for c in range(1, width):
            vals = []
            for i, r in enumerate(rows[1:end], start=1):
                label = _cell_text(r[0]).lower()
                if re.search(r"\b(sub-?total|less|add|note|schedule)\b", label):
                    continue
                v = _num(r[c])
                if v is not None:
                    vals.append((i, v))
            if total_idx is not None and len(vals) >= 2:
                total = _num(rows[total_idx][c])
                if total is not None:
                    expected = sum(v for _, v in vals)
                    ok = abs(expected - total) <= max(2.0, abs(total) * 0.01)
                    checks.append({"check": "column_sum", "column": c,
                                   "rows": [i for i, _ in vals],
                                   "expected": round(expected, 2), "reported": total,
                                   "passed": ok})
        # Row-wise total when the last column is explicitly a total column.
        if width >= 3:
            header = [_cell_text(x).lower() for x in rows[0]]
            if re.search(r"\btotal\b", header[-1]):
                for i, r in enumerate(rows[1:], start=1):
                    body = [_num(r[c]) for c in range(1, width - 1)]
                    body = [v for v in body if v is not None]
                    reported = _num(r[-1])
                    if body and reported is not None:
                        expected = sum(body)
                        ok = abs(expected - reported) <= max(2.0, abs(reported) * 0.01)
                        checks.append({"check": "row_sum", "row": i, "expected": round(expected, 2),
                                       "reported": reported, "passed": ok})
        passed = sum(1 for x in checks if x["passed"])
        status = "verified" if checks and passed == len(checks) else (
            "arithmetic_ok" if checks and passed >= max(1, len(checks) // 2) else "needs_review")
        return checks, status

    def write_parsed(self, result: dict, out_dir: Path, slug: str,
                     doc_type: str) -> dict:
        """Write the same pages.jsonl/document.md/meta.json layout as parse.py."""
        from .parse import classify_page

        out_dir.mkdir(parents=True, exist_ok=True)
        pages_jsonl = out_dir / "pages.jsonl"
        md_path = out_dir / "document.md"
        section = "front_matter"
        md_parts = [
            f"# {slug} — {doc_type}\n\nSource: `{result['profile']['file']}` · "
            f"SHA-256 `{result['profile']['sha256']}` · {result['profile']['pages']} pages\n"
        ]
        ocr_pages = []
        page_records = []
        with open(pages_jsonl, "w") as fj:
            for page in result["pages"]:
                text = page.get("text", "")
                section, is_heading = classify_page(text, section)
                tables = [t.get("grid", []) for t in page.get("tables", [])]
                rec = {
                    "page": page["page"], "page_label": "",
                    "text": text, "section": section,
                    "route": page.get("route", ""),
                    "route_reason": page.get("route_reason", ""),
                    "quality_score": page.get("quality_score", 0.0),
                    "tables": tables, "ocr": page.get("route") == "scanned",
                    "ocr_confidence": page.get("ocr_confidence"),
                    "engine": page.get("engine", ""),
                }
                page_records.append(rec)
                if rec["ocr"]:
                    ocr_pages.append({"page": rec["page"], "engine": rec["engine"],
                                      "confidence": rec["ocr_confidence"]})
                fj.write(json.dumps(rec) + "\n")
                md_parts.append(f"\n<!-- page: {rec['page']} route: {rec['route']} "
                                f"engine: {rec['engine']} -->\n\n{text.strip()}\n")
                for ti, grid in enumerate(tables, 1):
                    if not grid:
                        continue
                    width = max(len(r) for r in grid)
                    rows = [r + [""] * (width - len(r)) for r in grid]
                    md_parts.append(f"\n**Table {rec['page']}.{ti}**\n\n")
                    md_parts.append("| " + " | ".join(rows[0]) + " |\n")
                    md_parts.append("|" + "---|" * width + "\n")
                    for r in rows[1:]:
                        md_parts.append("| " + " | ".join(r) + " |\n")
        md_path.write_text("".join(md_parts))
        meta = {
            "slug": slug, "doc_type": doc_type,
            "file": result["profile"]["file"], "sha256": result["profile"]["sha256"],
            "pages": result["profile"]["pages"],
            "processed_pages": result["profile"]["processed_pages"],
            "ocr_pages": ocr_pages,
            "processing_seconds": result.get("elapsed_s", 0),
            "engine": "hybrid (PyMuPDF + Tesseract/PaddleOCR + Docling)",
            "markdown": str(md_path), "pages_jsonl": str(pages_jsonl),
            "sections": sorted({r["section"] for r in page_records if r.get("section")}),
            "summary": result.get("summary", {}),
            "warnings": [],
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
        return meta

    # ---------- main ----------
    def extract(self, path: Path, out_dir: Path | None = None, max_pages: int | None = None,
                start_page: int = 1) -> dict:
        path = Path(path)
        out_dir = Path(out_dir) if out_dir else config.STRUCTURED / "production" / path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tables").mkdir(exist_ok=True)
        doc = fitz.open(path)
        first = max(1, start_page)
        last = doc.page_count if max_pages is None else min(first + max_pages - 1, doc.page_count)
        profile = {"file": str(path), "sha256": sha256_file(path), "pages": doc.page_count,
                   "processed_pages": max(0, last - first + 1), "dpi": self.dpi,
                   "config": {"deskew": self.deskew, "force_ocr": self.force_ocr,
                              "docling_statements": self.docling_statements}}
        results: list[PageResult] = []
        md = [f"# Extracted document\n\nSource: `{path}` · SHA-256 `{profile['sha256']}` · pages {first}-{last}\n"]
        t0 = time.perf_counter()
        for i in range(first - 1, last):
            page = doc[i]
            p0 = time.perf_counter()
            page_w, page_h = page.rect.width, page.rect.height
            tables: list[TableResult] = []
            warnings: list[str] = []
            try:
                route, route_reason, quality = self._route_details(page)
                ocr_confidence = None
                ocr_items: list[dict] = []
                if route == "blank":
                    text, engine = "", "blank"
                elif route == "digital":
                    text = page.get_text("text", sort=True)
                    engine = "pymupdf_native"
                    try:
                        for t in page.find_tables().tables:
                            grid = [[_cell_text(c) for c in row] for row in t.extract()]
                            if len(grid) >= 2:
                                checks, status = self._validate_table(grid)
                                tables.append(TableResult(grid, "pymupdf", list(t.bbox), checks, status))
                    except Exception as e:
                        warnings.append(f"pymupdf_table:{e}")
                    native_numeric = sum(1 for t in tables for row in t.grid for c in row
                                         if _num(c) is not None)
                    if (self.docling_statements and STATEMENT_HINTS.search(text)
                            and (not tables or native_numeric < 4)):
                        spdf = self._page_pdf(page, out_dir / "pages")
                        for t in self._docling_tables(spdf, i + 1):
                            checks, status = self._validate_table(t["grid"])
                            tables.append(TableResult(t["grid"], "docling", None, checks, status))
                else:
                    img, spdf = self._render(page, out_dir / "pages")
                    pre = self._preprocess(img)
                    # Fast path: Tesseract first. Escalate to PaddleOCR only
                    # for low-confidence pages or table-heavy statements.
                    text, ocr_items, ocr_confidence = self._tesseract_page(pre, page_w, page_h)
                    engine = "tesseract"
                    low_conf = ocr_confidence < self.tesseract_confidence_min
                    try:
                        native_table_hint = bool(page.find_tables().tables)
                    except Exception:
                        native_table_hint = False
                    table_like = bool(STATEMENT_HINTS.search(text)) or native_table_hint
                    if self.ocr_engine == "paddle" or (
                            self.ocr_engine == "auto" and (low_conf or not text.strip()
                                                           or (table_like and len(ocr_items) < 8))):
                        text, ocr_items = self._paddle_page(pre, page_w, page_h)
                        engine = "paddleocr"
                    if self.docling_statements and (STATEMENT_HINTS.search(text) or table_like):
                        for t in self._docling_tables(spdf, i + 1):
                            grid = self._fuse_table(t, ocr_items)
                            checks, status = self._validate_table(grid)
                            tables.append(TableResult(grid, f"docling+{engine}_fusion", None,
                                                      checks, status))
                    elif not text.strip():
                        warnings.append("empty_ocr_text")
                pr = PageResult(i + 1, route, text, engine, tables, time.perf_counter() - p0,
                                warnings, route_reason, quality, ocr_confidence)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                warnings.append(msg)
                pr = PageResult(i + 1, "error", "", "none", [], time.perf_counter() - p0,
                                warnings, "exception", 0.0, None)
            results.append(pr)
            md.append(f"\n<!-- page: {i+1} label: {page.get_label() or ''} "
                      f"route: {pr.route} engine: {pr.engine} -->\n\n{pr.text.strip()}\n")
            for ti, t in enumerate(pr.tables, 1):
                md.append(f"\n**Table {i+1}.{ti} ({t.engine}, {t.status})**\n\n")
                if t.grid:
                    w = max(len(r) for r in t.grid)
                    rows = [r + [""] * (w - len(r)) for r in t.grid]
                    md.append("| " + " | ".join(rows[0]) + " |\n")
                    md.append("|" + "---|" * w + "\n")
                    for r in rows[1:]:
                        md.append("| " + " | ".join(r) + " |\n")
                with open(out_dir / "tables" / f"p{i+1:04d}_t{ti}.csv", "w", newline="") as f:
                    csv.writer(f).writerows(t.grid)
            if len(results) % 10 == 0:
                (out_dir / "result.partial.json").write_text(json.dumps({
                    "profile": profile, "pages_done": len(results),
                    "pages": [r.to_dict() for r in results],
                }, indent=1))
        elapsed = time.perf_counter() - t0
        (out_dir / "document.md").write_text("".join(md))
        result = {
            "profile": profile,
            "elapsed_s": round(elapsed, 2),
            "pages": [r.to_dict() for r in results],
            "summary": {
                "digital_pages": sum(r.route == "digital" for r in results),
                "scanned_pages": sum(r.route == "scanned" for r in results),
                "blank_pages": sum(r.route == "blank" for r in results),
                "tesseract_pages": sum(r.engine == "tesseract" for r in results),
                "paddle_pages": sum(r.engine == "paddleocr" for r in results),
                "tables": sum(len(r.tables) for r in results),
                "tables_verified": sum(t.status in ("verified", "arithmetic_ok")
                                       for r in results for t in r.tables),
                "tables_needs_review": sum(t.status == "needs_review"
                                           for r in results for t in r.tables),
                "warnings": sum(len(r.warnings) for r in results),
                "error_pages": sum(r.route == "error" for r in results),
            },
        }
        (out_dir / "result.json").write_text(json.dumps(result, indent=1))
        (out_dir / "result.partial.json").unlink(missing_ok=True)
        return result


def main():
    ap = argparse.ArgumentParser(description="Hybrid production document extractor")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--no-deskew", action="store_true")
    ap.add_argument("--force-ocr", action="store_true")
    ap.add_argument("--no-docling-statements", action="store_true")
    ap.add_argument("--ocr-engine", choices=["auto", "tesseract", "paddle"], default="auto")
    ap.add_argument("--tesseract-confidence-min", type=float, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    ex = HybridExtractor(dpi=args.dpi, deskew=not args.no_deskew, force_ocr=args.force_ocr,
                         docling_statements=not args.no_docling_statements,
                         ocr_engine=args.ocr_engine,
                         tesseract_confidence_min=args.tesseract_confidence_min)
    res = ex.extract(args.pdf, args.out, args.max_pages, args.start_page)
    print(json.dumps(res["summary"], indent=1))
    print("output:", args.out or (config.STRUCTURED / "production" / args.pdf.stem))


if __name__ == "__main__":
    main()
