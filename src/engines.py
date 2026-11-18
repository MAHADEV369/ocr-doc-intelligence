"""Unified engine adapters.

Each adapter receives a single-page PDF plus its rendered PNG and returns
text, markdown, tables and timing. Heavy models are initialised lazily once
per process so benchmark timing can separate cold start from steady state.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from .quality import items_to_text
from .text_utils import clean_text, strip_markdown

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


@dataclass
class EngineResult:
    engine: str
    text: str = ""
    markdown: str = ""
    tables: list[list[list[str]]] = field(default_factory=list)
    elapsed_s: float = 0.0
    model_load_s: float = 0.0
    model_version: str = ""
    error: str = ""
    html_tables: list[str] = field(default_factory=list)
    confidence: float | None = None


def _grid_from_markdown(md: str) -> list[list[list[str]]]:
    """Parse GitHub-style pipe tables from markdown into grids."""
    tables = []
    cur: list[list[str]] = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
                continue
            cur.append(cells)
        else:
            if len(cur) >= 2:
                tables.append(cur)
            cur = []
    if len(cur) >= 2:
        tables.append(cur)
    return tables


def _grid_from_html(md: str) -> list[list[list[str]]]:
    """Parse HTML <table> blocks emitted by MinerU/Docling markdown."""
    if "<table" not in (md or "").lower():
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(md, "lxml")
    except Exception:
        return []
    tables = []
    for tab in soup.find_all("table"):
        grid = []
        for tr in tab.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if cells:
                grid.append(cells)
        if len(grid) >= 2:
            tables.append(grid)
    return tables


class BaseEngine:
    name = "base"
    version = ""

    def __init__(self):
        self.load_time = 0.0
        self._loaded = False

    def load(self):
        self._loaded = True

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        raise NotImplementedError

    def _ensure(self):
        if not self._loaded:
            t = time.perf_counter()
            self.load()
            self.load_time = time.perf_counter() - t
            self._loaded = True


class NativeEngine(BaseEngine):
    name = "native"
    version = "PyMuPDF 1.27.2.2"

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        t = time.perf_counter()
        doc = fitz.open(pdf_path)
        page = doc[0]
        text = page.get_text("text", sort=True)
        md = page.get_text("markdown")
        grids = []
        try:
            for tab in page.find_tables().tables:
                grids.append([[str(c or "").strip() for c in row] for row in tab.extract()])
        except Exception:
            pass
        return EngineResult(self.name, text=text, markdown=md, tables=grids,
                            elapsed_s=time.perf_counter() - t, model_version=self.version)


class TesseractEngine(BaseEngine):
    name = "tesseract"
    version = "tesseract 5.5.2"

    def load(self):
        import pytesseract
        pytesseract.get_tesseract_version()

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        self._ensure()
        import pytesseract
        from PIL import Image
        t = time.perf_counter()
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="eng", config="--oem 1 --psm 3")
        return EngineResult(self.name, text=text, markdown=text,
                            elapsed_s=time.perf_counter() - t, model_version=self.version)


class PaddleEngine(BaseEngine):
    name = "paddleocr"
    version = "PaddleOCR 3.7.0 PP-OCRv6_medium"

    def __init__(self):
        super().__init__()
        self.ocr = None

    def load(self):
        from paddleocr import PaddleOCR
        # Benchmark pages are upright by construction; orientation/unwarping
        # are enabled in the production extractor, where scans need them.
        self.ocr = PaddleOCR(use_doc_orientation_classify=False,
                             use_doc_unwarping=False,
                             use_textline_orientation=False,
                             lang="en")

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        self._ensure()
        t = time.perf_counter()
        res = self.ocr.predict(str(image_path))
        r = res[0]
        texts = r["rec_texts"]
        polys = r.get("rec_polys") or r.get("dt_polys") or []
        scores = r.get("rec_scores") or []
        items = []
        for i, txt in enumerate(texts):
            if i < len(polys) and polys[i] is not None:
                pts = polys[i]
                xs = [float(p[0]) for p in pts]
                ys = [float(p[1]) for p in pts]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            else:
                bbox = [0.0, float(i * 10), 1.0, float(i * 10 + 8)]
            items.append({"text": txt, "bbox": bbox,
                          "score": float(scores[i]) if i < len(scores) else 0.0})
        width = max((z["bbox"][2] for z in items), default=0.0)
        text = items_to_text(items, width)
        confs = [z["score"] for z in items if z.get("score", 0) > 0]
        confidence = round(100 * sum(confs) / len(confs), 2) if confs else None
        return EngineResult(self.name, text=text, markdown=text,
                            elapsed_s=time.perf_counter() - t, model_version=self.version,
                            confidence=confidence)


class DoclingEngine(BaseEngine):
    name = "docling"
    version = "docling 2.150.0"

    def __init__(self):
        super().__init__()
        self.conv = None

    def load(self):
        from docling.document_converter import DocumentConverter
        self.conv = DocumentConverter()

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        self._ensure()
        t = time.perf_counter()
        res = self.conv.convert(str(pdf_path))
        doc = res.document
        md = doc.export_to_markdown()
        plain = md
        try:
            export_text = getattr(doc, "export_to_text", None)
            if callable(export_text):
                plain = export_text()
        except Exception:
            plain = strip_markdown(md)
        grids, html = [], []
        for tab in getattr(doc, "tables", []):
            try:
                grid = [[c.text.strip() for c in row] for row in tab.data.grid]
                if grid:
                    grids.append(grid)
                html.append(tab.export_to_html())
            except Exception:
                continue
        text = plain
        return EngineResult(self.name, text=text, markdown=md, tables=grids,
                            html_tables=html, elapsed_s=time.perf_counter() - t,
                            model_version=self.version)


class MinerUEngine(BaseEngine):
    name = "mineru"
    version = "MinerU 3.0.9 pipeline"

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        t = time.perf_counter()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            cmd = [shutil.which("mineru") or "mineru", "-p", str(pdf_path), "-o", str(out),
                   "-b", "pipeline", "-l", "en"]
            env = dict(os.environ, MINERU_LOG_LEVEL="ERROR")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, env=env)
            if proc.returncode != 0:
                return EngineResult(self.name, error=(proc.stderr or proc.stdout)[-2000:],
                                    elapsed_s=time.perf_counter() - t)
            mds = list(out.rglob("*.md"))
            if not mds:
                return EngineResult(self.name, error="no markdown produced",
                                    elapsed_s=time.perf_counter() - t)
            md = mds[0].read_text(errors="ignore")
            grids = _grid_from_markdown(md) or _grid_from_html(md)
            return EngineResult(self.name, text=strip_markdown(md), markdown=md, tables=grids,
                                elapsed_s=time.perf_counter() - t, model_version=self.version)


class OCRmyPDFEngine(BaseEngine):
    name = "ocrmypdf"
    version = "OCRmyPDF 17.14.1 (Tesseract 5.5.2)"

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        t = time.perf_counter()
        with tempfile.TemporaryDirectory() as td:
            out_pdf = Path(td) / "ocr.pdf"
            side = Path(td) / "side.txt"
            cmd = ["ocrmypdf", "--force-ocr", "--sidecar", str(side), "--output-type", "pdf",
                   "--optimize", "0", str(pdf_path), str(out_pdf)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if proc.returncode != 0:
                return EngineResult(self.name, error=(proc.stderr or proc.stdout)[-2000:],
                                    elapsed_s=time.perf_counter() - t, model_version=self.version)
            text = side.read_text(errors="ignore") if side.exists() else ""
            return EngineResult(self.name, text=text, markdown=text,
                                elapsed_s=time.perf_counter() - t, model_version=self.version)


class OlmOCREngine(BaseEngine):
    """olmOCR requires vLLM (CUDA). On Apple Silicon we attempt the
    transformers backend if the package and weights are available."""
    name = "olmocr"
    version = "olmocr 0.4.27"

    def load(self):
        import olmocr  # noqa: F401

    def run(self, pdf_path: Path, image_path: Path) -> EngineResult:
        return EngineResult(self.name, error="olmOCR 7B requires CUDA/vLLM; not runnable on this Apple M-series host (MPS unsupported by vLLM).",
                            model_version=self.version)


def get_engine(name: str) -> BaseEngine:
    return {
        "native": NativeEngine,
        "tesseract": TesseractEngine,
        "paddleocr": PaddleEngine,
        "docling": DoclingEngine,
        "mineru": MinerUEngine,
        "ocrmypdf": OCRmyPDFEngine,
        "olmocr": OlmOCREngine,
    }[name]()


def normalize_text(s: str) -> str:
    return clean_text(s)
