"""Resolve document metadata (period, source path, SHA-256) from manifests.

The extraction modules used to hard-code FY2025-26, Q2 FY2026-27 and source
paths. This module makes those values data-driven so a new filing is picked up
from the manifest instead of a code edit.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import config


@dataclass(frozen=True)
class DocumentMeta:
    slug: str
    company: str
    doc_type: str
    financial_year: str
    report_period: str
    source_document: str
    sha256: str
    pages: int
    period_raw: str
    title: str


def parse_financial_year(text: str) -> str:
    """Return FY2025-26 style from text such as 'FY2025-26' or '2025-2026'."""
    if not text:
        return ""
    m = re.search(r"\bfy\s*(\d{4})\s*[-–/]\s*(\d{2,4})\b", text, re.I)
    if m:
        start = m.group(1)
        end = m.group(2)
        if len(end) == 4:
            end = end[-2:]
        elif len(end) == 1:
            end = "0" + end
        return f"FY{start}-{end}"
    m = re.search(r"\b(20\d{2})\s*[-–/]\s*(20\d{2})\b", text)
    if m:
        return f"FY{m.group(1)}-{m.group(2)[-2:]}"
    return ""


def _period_end(text: str) -> str:
    """Convert 'year ended 31 March 2026' to a clean report period."""
    m = re.search(
        r"(year|quarter|period)\s+ended?\s+(\d{1,2})\s+"
        r"(january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\s+(\d{4})",
        text or "",
        re.I,
    )
    if not m:
        return ""
    kind = m.group(1).capitalize()
    day = m.group(2)
    month = m.group(3).capitalize()
    year = m.group(4)
    return f"{kind} ended {day} {month} {year}"


def _fallback_period(doc_type: str) -> tuple[str, str]:
    if doc_type == "annual_report":
        return "FY2025-26", "Year ended 31 March 2026"
    if doc_type == "quarterly_results":
        return "FY2026-27", "Quarter ended 30 September 2026"
    return "FY2026-27", "Quarter ended 30 September 2026"


@lru_cache(maxsize=64)
def manifest(slug: str) -> dict:
    path = config.MANIFESTS / f"{slug}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def document(slug: str, doc_type: str) -> DocumentMeta | None:
    m = manifest(slug)
    if not m:
        return None
    for d in m.get("documents", []):
        if d.get("doc_type") != doc_type:
            continue
        raw = d.get("period", "") or ""
        fy = parse_financial_year(raw) or _fallback_period(doc_type)[0]
        rp = _period_end(raw)
        if not rp:
            rp = _fallback_period(doc_type)[1]
        return DocumentMeta(
            slug=slug,
            company=m.get("company", config.COMPANY_BY_SLUG.get(slug, {}).get("name", slug)),
            doc_type=doc_type,
            financial_year=fy,
            report_period=rp,
            source_document=d.get("file", f"data/raw/{slug}/{doc_type}.pdf"),
            sha256=d.get("sha256", ""),
            pages=int(d.get("pages", 0) or 0),
            period_raw=raw,
            title=d.get("title", ""),
        )
    return None


def annual_meta(slug: str) -> DocumentMeta:
    return document(slug, "annual_report") or DocumentMeta(
        slug=slug,
        company=config.COMPANY_BY_SLUG.get(slug, {}).get("name", slug),
        doc_type="annual_report",
        financial_year="FY2025-26",
        report_period="Year ended 31 March 2026",
        source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
        sha256="",
        pages=0,
        period_raw="",
        title="",
    )


def quarter_meta(slug: str) -> DocumentMeta:
    return document(slug, "quarterly_results") or DocumentMeta(
        slug=slug,
        company=config.COMPANY_BY_SLUG.get(slug, {}).get("name", slug),
        doc_type="quarterly_results",
        financial_year="FY2026-27",
        report_period="Quarter ended 30 September 2026",
        source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
        sha256="",
        pages=0,
        period_raw="",
        title="",
    )


def presentation_meta(slug: str) -> DocumentMeta:
    return document(slug, "investor_presentation") or DocumentMeta(
        slug=slug,
        company=config.COMPANY_BY_SLUG.get(slug, {}).get("name", slug),
        doc_type="investor_presentation",
        financial_year="FY2026-27",
        report_period="Quarter ended 30 September 2026",
        source_document=f"data/raw/{slug}/q2_fy2027_presentation.pdf",
        sha256="",
        pages=0,
        period_raw="",
        title="",
    )


def source_path(meta: DocumentMeta) -> Path:
    return config.ROOT / meta.source_document
