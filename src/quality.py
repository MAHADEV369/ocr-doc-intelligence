"""Page-quality heuristics and layout-aware line ordering.

These helpers deliberately avoid a single magic threshold. A page is routed
using several independent signals: native character count, image coverage,
dictionary-word quality, numeric-token quality and known vendor-OCR artefacts.
"""
from __future__ import annotations

import re

import fitz

ARTEFACTS = {
    "operntions", "penxl", "depredation", "jlems", "revenue from operntions",
    "profit for the pen", "partlculars", "partlcular", "flnancial", "statemenl",
    "lncome", "expencliture", "olher", "olher income", "balancc",
}
VOWELS = re.compile(r"[aeiouy]", re.I)
ALPHA_TOKEN = re.compile(r"[A-Za-z]{2,}")
NUMERIC_CONFUSION = re.compile(r"\b(?:\d[OoIl]|[OoIl]\d)[\dOoIl,.]*\b")


def text_quality_score(text: str) -> float:
    """0..1 heuristic; lower means more likely a broken OCR text layer."""
    t = text or ""
    if len(t.strip()) < 40:
        return 0.0
    words = t.split()
    alpha = ALPHA_TOKEN.findall(t)
    if not words:
        return 0.0
    if not alpha:
        # A page of table numbers can still be a perfectly good digital text
        # layer; do not force OCR just because there are no words.
        numeric = re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", t)
        return 0.7 if len(numeric) >= 10 else 0.0
    vowel_words = sum(1 for w in alpha if len(w) >= 3 and VOWELS.search(w))
    vowel_ratio = vowel_words / len(alpha)
    long_consonants = sum(1 for w in alpha if re.search(r"[bcdfghjklmnpqrstvwxz]{5,}", w, re.I))
    consonant_penalty = long_consonants / len(alpha)
    mixed_alnum = len(NUMERIC_CONFUSION.findall(t))
    artefact_hits = sum(1 for a in ARTEFACTS if re.search(rf"\b{re.escape(a)}\b", t, re.I))
    numeric_tokens = re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", t)
    numeric_ratio = len(numeric_tokens) / max(1, len(words))
    score = (
        0.45 * vowel_ratio
        + 0.25 * (1.0 - min(1.0, consonant_penalty * 3))
        + 0.20 * (1.0 - min(1.0, artefact_hits / 3))
        + 0.10 * (1.0 - min(1.0, mixed_alnum / 8))
    )
    # A page with a healthy amount of numeric and alphabetic content is more
    # likely to be a real text layer; very low numeric ratio is not penalised
    # because narrative pages legitimately have few numbers.
    if numeric_ratio > 0.02:
        score = min(1.0, score + 0.05)
    return round(max(0.0, min(1.0, score)), 4)


def image_coverage(page: fitz.Page) -> float:
    """Fraction of the page covered by raster images (capped at 1)."""
    try:
        area = abs(page.rect.width * page.rect.height) or 1.0
        total = 0.0
        for img in page.get_images(full=True):
            xref = img[0]
            for r in page.get_image_rects(xref):
                total += abs(r.width * r.height)
        return round(min(1.0, total / area), 4)
    except Exception:
        return 0.0


def route_page(page: fitz.Page, force_ocr: bool = False) -> tuple[str, str, float]:
    """Return (route, reason, quality_score)."""
    if force_ocr:
        return "scanned", "force_ocr", 0.0
    text = page.get_text("text")
    chars = len(text.strip())
    quality = text_quality_score(text)
    coverage = image_coverage(page)
    if chars == 0:
        try:
            has_image = bool(page.get_images(full=True))
        except Exception:
            has_image = False
        if not has_image:
            return "blank", "no_text_or_image", quality
        return "scanned", "no_native_text", quality
    if coverage >= 0.65 and (chars < 800 or quality < 0.75):
        return "scanned", f"image_coverage={coverage:.2f}", quality
    if quality < 0.45:
        return "scanned", f"low_text_quality={quality:.2f}", quality
    if chars < 120:
        return "scanned", f"sparse_text={chars}", quality
    return "digital", f"quality={quality:.2f},coverage={coverage:.2f}", quality


def _split_columns(items: list[dict], page_width: float) -> list[list[dict]]:
    """Split items into visual columns when a clear vertical gutter exists."""
    if len(items) < 4 or page_width <= 0:
        return [items]
    ordered = sorted(items, key=lambda z: (z["bbox"][0] + z["bbox"][2]) / 2)
    centers = [(z["bbox"][0] + z["bbox"][2]) / 2 for z in ordered]
    best_gap, split = 0.0, None
    for i in range(1, len(centers)):
        gap = centers[i] - centers[i - 1]
        if gap > best_gap:
            best_gap, split = gap, i
    if split is None or best_gap < page_width * 0.12:
        return [items]
    left = ordered[:split]
    right = ordered[split:]
    if len(left) < 2 or len(right) < 2:
        return [items]
    return [left, right]


def looks_table_like(items: list[dict]) -> bool:
    """Short numeric boxes dominate tables; prose boxes do not."""
    if not items:
        return False
    numeric = sum(1 for z in items if re.fullmatch(r"[\(\)\d,.\-–—%]+", z.get("text", "").strip()))
    short = sum(1 for z in items if len(z.get("text", "").strip()) <= 24)
    return numeric / len(items) >= 0.18 and short / len(items) >= 0.45


def order_items(items: list[dict], page_width: float = 0.0,
                table_mode: bool | None = None) -> list[dict]:
    """Order OCR items by visual columns then top-to-bottom within each column.

    Tables are read row-wise: splitting a financial table into visual columns
    would put every label before every number. Narrative pages use an XY-cut so
    two-column prose is not interleaved.
    """
    if not items:
        return []
    if table_mode is None:
        table_mode = looks_table_like(items)
    if table_mode:
        return sorted(items, key=lambda z: ((z["bbox"][1] + z["bbox"][3]) / 2, z["bbox"][0]))
    width = page_width or max(z["bbox"][2] for z in items)
    columns = _split_columns(items, width)
    if len(columns) == 1:
        return sorted(items, key=lambda z: ((z["bbox"][1] + z["bbox"][3]) / 2, z["bbox"][0]))
    out: list[dict] = []
    for col in columns:
        out.extend(sorted(col, key=lambda z: ((z["bbox"][1] + z["bbox"][3]) / 2, z["bbox"][0])))
    return out


def items_to_text(items: list[dict], page_width: float = 0.0) -> str:
    ordered = order_items(items, page_width)
    lines: list[list[dict]] = []
    for item in ordered:
        cy = (item["bbox"][1] + item["bbox"][3]) / 2
        if lines and abs(((lines[-1][0]["bbox"][1] + lines[-1][0]["bbox"][3]) / 2) - cy) <= 4.5:
            lines[-1].append(item)
        else:
            lines.append([item])
    return "\n".join(" ".join(i["text"] for i in sorted(line, key=lambda z: z["bbox"][0]))
                     for line in lines)
