"""Document ingestion: hash, page count, digital/scanned classification, page rendering."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz

from . import config
from .quality import image_coverage, route_page, text_quality_score
from .schemas import DocumentProfile, PageProfile


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def profile_document(path: Path, sample_all: bool = True, doc=None) -> DocumentProfile:
    doc = doc or fitz.open(path)
    profiles: list[PageProfile] = []
    pages = range(doc.page_count) if sample_all else range(min(20, doc.page_count))
    for i in pages:
        page = doc[i]
        text = page.get_text("text")
        chars = len(text.strip())
        words = len(text.split())
        images = len(page.get_images(full=True))
        drawings = len(page.get_drawings())
        if chars == 0 and images == 0 and drawings == 0:
            kind = "blank"
        elif chars >= config.DIGITAL_TEXT_MIN_CHARS:
            kind = "digital" if images <= 3 else "mixed"
        elif images > 0 or chars > 0:
            kind = "scanned" if chars < config.DIGITAL_TEXT_MIN_CHARS else "mixed"
        else:
            kind = "blank"
        route, reason, quality = route_page(page)
        try:
            has_tables = bool(page.find_tables().tables) if chars >= config.DIGITAL_TEXT_MIN_CHARS else False
        except Exception:
            has_tables = False
        profiles.append(PageProfile(
            page=i + 1, chars=chars, words=words, images=images, kind=kind,
            has_tables=has_tables, route=route, route_reason=reason,
            quality_score=quality, image_coverage=image_coverage(page),
        ))
    counts = {k: sum(1 for p in profiles if p.kind == k) for k in ("digital", "scanned", "mixed", "blank")}
    return DocumentProfile(
        file=str(path.relative_to(config.ROOT)) if path.is_relative_to(config.ROOT) else str(path),
        sha256=sha256_file(path),
        pages=doc.page_count,
        digital_pages=counts["digital"],
        scanned_pages=counts["scanned"],
        mixed_pages=counts["mixed"],
        blank_pages=counts["blank"],
        page_profiles=profiles,
        native_chars_total=sum(p.chars for p in profiles),
        is_scanned_majority=counts["scanned"] > max(1, len(profiles) // 2),
    )


def render_page(path: Path, page_no: int, out_dir: Path, dpi: int = config.RENDER_DPI,
                doc=None) -> Path:
    """Render a 1-based page number to PNG."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (f"p{page_no:04d}.png" if dpi == config.RENDER_DPI
                     else f"p{page_no:04d}_{dpi}.png")
    if out.exists() and out.stat().st_size > 0:
        return out
    doc = doc or fitz.open(path)
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    pix.save(out)
    return out


def single_page_pdf(path: Path, page_no: int, out_dir: Path, doc=None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"p{page_no:04d}.pdf"
    if out.exists() and out.stat().st_size > 0:
        return out
    doc = doc or fitz.open(path)
    new = fitz.open()
    new.insert_pdf(doc, from_page=page_no - 1, to_page=page_no - 1)
    new.save(out)
    new.close()
    return out


def page_native_text(path: Path, page_no: int, doc=None) -> str:
    doc = doc or fitz.open(path)
    return doc[page_no - 1].get_text("text")


def page_label(path: Path, page_no: int, doc=None) -> str:
    """Printed page label (e.g. 476) rather than the PDF index (e.g. 471)."""
    try:
        doc = doc or fitz.open(path)
        return doc[page_no - 1].get_label() or str(page_no)
    except Exception:
        return str(page_no)


def text_quality(text: str) -> float:
    return text_quality_score(text)


def iter_manifest(slug: str | None = None):
    for f in sorted(config.MANIFESTS.glob("*.json")):
        if slug and f.stem != slug:
            continue
        data = json.loads(f.read_text())
        for d in data.get("documents", []):
            if d.get("status", "downloaded") != "downloaded":
                continue
            fp = config.ROOT / d["file"]
            if fp.exists():
                yield data, d, fp


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    prof = profile_document(p)
    print(prof.model_dump_json(indent=2))
