"""Build a small degraded-scan set to test robustness (150 DPI, JPEG, rotation, noise)."""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageFilter

from src import config

BENCH = config.BENCHMARK


def degrade(src: Path, dst: Path):
    img = Image.open(src).convert("RGB")
    img = img.rotate(0.7, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    img = img.resize((int(img.width * 0.8), int(img.height * 0.8)), Image.LANCZOS)
    tmp = dst.with_suffix(".jpg")
    img.save(tmp, quality=50, optimize=True)
    img = Image.open(tmp).convert("RGB")
    arr = np.asarray(img).astype(np.int16)
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 7, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.3))
    img.save(dst)


def build():
    manifest = json.loads((BENCH / "manifest.json").read_text())
    selected = [p for p in manifest if p["kind"] == "financial_table"][:8]
    out = []
    for p in selected:
        d = BENCH / "degraded" / p["slug"]
        d.mkdir(parents=True, exist_ok=True)
        img = d / "page.png"
        degrade(Path(p["image"]), img)
        pdf = d / "page.pdf"
        fitz_img = Image.open(img)
        doc = fitz.open()
        pg = doc.new_page(width=fitz_img.width * 72 / 150, height=fitz_img.height * 72 / 150)
        pg.insert_image(pg.rect, filename=str(img))
        doc.save(pdf)
        doc.close()
        out.append({**p, "image": str(img), "single_page_pdf": str(pdf), "degraded": True})
    (BENCH / "manifest_degraded.json").write_text(json.dumps(out, indent=1))
    print("degraded pages", len(out))


if __name__ == "__main__":
    build()
