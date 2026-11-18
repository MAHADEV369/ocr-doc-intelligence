"""Quarterly results extraction (Q2 FY2026-27, consolidated where available)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from . import config, periods
from .schemas import ExtractedField, ReportingBasis, ValidationStatus, ValueStatus
from .statements import (
    Line,
    clean_label,
    find_rows,
    is_nil_source,
    load_lines,
    page_labels,
    pick,
    table_find,
    visual_find,
)
from .units import UnitInfo, detect_unit

# Fallbacks used while building records; the post-pass in extract_quarter()
# replaces them with values resolved from the document manifest.
FIN_YEAR = "FY2026-27"
PERIOD = "Quarter ended 30 September 2026"

QFIELDS = {
    "revenue": [r"^revenue from operations?\b", r"^gross revenue\b", r"^sales\b", r"^revenue\b",
                r"^total revenue from operations\b"],
    "total_income": [r"^total income\b", r"^total revenue\b"],
    "ebitda": [r"^ebitda\b"],
    "depreciation_amortisation": [r"^depreciation\b"],
    "finance_costs": [r"^finance costs?\b", r"^interest expense\b"],
    "pbt": [r"^profit before tax\b", r"^profit before exceptional items and tax\b", r"^profit.*before tax\b"],
    "tax_expense": [r"^tax expense\b", r"^total tax expense\b"],
    "current_tax": [r"^current tax\b"],
    "deferred_tax": [r"^deferred tax\b"],
    "pat": [r"^profit after tax\b", r"^net profit\b", r"^profit for the (?:period|quarter|year)\b",
            r"^profit for the pen", r"^profit.*for the (?:period|quarter|year)\b"],
    "eps_basic": [r"^basic\b", r"^earnings per (?:equity )?share\b", r"^\(a\) basic\b", r"^\(i\) basic\b"],
    "interest_income": [r"^interest earned\b", r"^interest income\b"],
    "interest_expense": [r"^interest expended\b", r"^interest expense\b"],
    "other_income": [r"^other income\b"],
    "operating_expenses": [r"^operating expenses\b"],
    "provisions": [r"^provisions?(?: and contingencies)?\b"],
    "revenue_alt": [r"^revenue from oper\b", r"^sales\b"],
}


def _pages(path: Path) -> list[tuple[int, str]]:
    doc = fitz.open(path)
    return [(i + 1, doc[i].get_text()) for i in range(doc.page_count)]


def select_pages(path: Path) -> list[int]:
    pages = _pages(path)
    scored = []
    for p, t in pages:
        low = re.sub(r"\s+", " ", t.lower())
        score = 0
        if "consolidated" in low:
            score += 15
        if "financial results" in low or "results for the quarter" in low:
            score += 4
        if "revenue from operations" in low or "interest earned" in low or "gross revenue" in low:
            score += 6
        if "profit before tax" in low or "profit before exceptional" in low:
            score += 4
        if "profit for the period" in low or "profit after tax" in low or "net profit" in low:
            score += 4
        if "ebitda" in low:
            score += 2
        if "highlights" in low:
            score += 5
        if "balance sheet" in low and "profit" not in low:
            score -= 8
        if "cash flow" in low and "profit before tax" not in low:
            score -= 6
        if score >= 14:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [scored[0][1]] if scored else [1]


def _ocr_lines(path: Path, pages: list[int]) -> tuple[list[Line], UnitInfo]:
    import pytesseract
    from PIL import Image
    doc = fitz.open(path)
    lines: list[Line] = []
    all_text = []
    for p in pages:
        pix = doc[p - 1].get_pixmap(dpi=config.OCR_DPI)
        tmp = config.PAGES / f"_ocr_q_{path.stem}_p{p}.png"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        pix.save(tmp)
        txt = pytesseract.image_to_string(Image.open(tmp), lang="eng",
                                         config=f"--oem 1 --psm 6 --dpi {config.OCR_DPI}")
        all_text.append(txt)
        for raw in txt.splitlines():
            s = re.sub(r"\s+", " ", raw).strip()
            if s:
                lines.append(Line(p, s, clean_label(s).lower()))
    text = " ".join(all_text)
    return lines, detect_unit(text)


def _parse(lines: list[Line], unit_info: UnitInfo, slug: str, kind: str, path: Path,
           page=None) -> list[ExtractedField]:
    out: list[ExtractedField] = []
    for fname, pats in QFIELDS.items():
        if fname == "revenue_alt":
            continue
        if kind == "bank" and fname in {"revenue", "ebitda", "depreciation_amortisation", "finance_costs"}:
            continue
        if kind != "bank" and fname in {"interest_income", "interest_expense", "operating_expenses", "provisions"}:
            continue
        hits = find_rows(lines, pats, drop_note_values=(fname != "eps_basic"))
        if page is not None and (not hits or fname == "revenue"):
            vhits = visual_find(page, pats) or table_find(page, pats)
            if vhits:
                cleaned = []
                for lab, nums, pg, raw in vhits:
                    while len(nums) > 1 and nums[0] == int(nums[0]) and abs(nums[0]) <= 60:
                        nums = nums[1:]
                    if nums:
                        cleaned.append((lab, nums, pg, raw))
                if cleaned:
                    hits = (hits + cleaned) if fname == "revenue" else (hits or cleaned)
        if not hits and fname == "revenue":
            hits = find_rows(lines, QFIELDS["revenue_alt"])
        if not hits:
            continue
        if fname == "eps_basic":
            hits = [h for h in hits if "basic" in clean_label(h[0]).lower() and h[1] and abs(h[1][0]) > 0.05]
            if not hits:
                continue
        if fname == "pat":
            def rank(h):
                lab = clean_label(h[0]).lower()
                if "before minority" in lab:
                    return 30
                for i, o in enumerate(["net profit for the period", "profit for the period", "net profit",
                                       "profit after tax", "profit for the pen"]):
                    if lab.startswith(o):
                        return i
                return 20
            hits = sorted(hits, key=rank)
        if fname == "revenue":
            pref = ["total revenue from operations", "revenue from operations", "gross revenue", "revenue", "sales"]
            hits = sorted(hits, key=lambda h: next(
                (i for i, o in enumerate(pref) if clean_label(h[0]).lower().startswith(o)), 99))
        h = hits[0] if fname == "revenue" else pick(hits, fname)
        label, vals, hit_page, src = h
        if not vals:
            continue
        cur = vals[0]
        priory = vals[2] if len(vals) >= 3 else (vals[1] if len(vals) > 1 else None)
        effective_mult = 1.0 if fname == "eps_basic" else unit_info.multiplier
        vstatus = (ValueStatus.nil if is_nil_source(src, cur) else ValueStatus.reported)
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
            reporting_basis=ReportingBasis.consolidated,
            field_name=fname, original_value=src, normalized_value=round(cur * effective_mult, 4),
            currency="INR",
            unit=("INR per share" if fname == "eps_basic" else unit_info.canonical_unit),
            source_value=cur,
            source_unit=("INR per share" if fname == "eps_basic" else unit_info.source_unit),
            scale_factor=effective_mult,
            source_page=hit_page,
            source_table="quarterly_results", source_text=src, value_status=vstatus,
            confidence=0.9 if len(vals) >= 3 else 0.75,
            confidence_method="label_regex+visual_row",
            validation_status=ValidationStatus.needs_review, extraction_engine="native_pymupdf",
            model_version="PyMuPDF 1.27.2.2", section="quarterly_results",
            notes=f"prior_year_quarter_value={round(priory * effective_mult, 4) if priory is not None else None}",
        ))
    return out


def extract_quarter(slug: str, path: Path) -> list[ExtractedField]:
    kind = config.COMPANY_BY_SLUG[slug]["kind"]
    meta = periods.quarter_meta(slug)
    labels = page_labels(path)
    pages = select_pages(path)
    lines, unit_info = load_lines(path, pages)
    doc = fitz.open(path)
    out = _parse(lines, unit_info, slug, kind, path, page=doc[pages[0] - 1])

    # OCR fallback for scanned/OCR-degraded results (e.g. Airtel Q2 PDF).
    page_text = "\n".join(t for _, t in _pages(path) if _ == pages[0])
    if len(out) < 5 and not re.search(r"revenue from operations", page_text, re.I):
        olines, ounit = _ocr_lines(path, pages)
        oout = _parse(olines, ounit, slug, kind, path)
        if len(oout) > len(out):
            out, unit_info = oout, ounit
    out = [f for f in out if f.field_name != "revenue_alt"]

    # ---- Sun Pharma press-release style (values stated in prose) ----
    if slug == "sunpharma":
        text = re.sub(r"\s+", " ", "\n".join(t for _, t in _pages(path)))
        patterns = {
            "revenue": r"Sales at Rs\.?\s*([\d,]+)\s*million",
            "ebitda": r"EBITDA at Rs\.?\s*([\d,]+)\s*million",
            "pbt": r"Profit before exceptional items and tax was Rs\.?\s*([\d,]+)\s*million",
            "pat": r"Net profit was Rs\.?\s*([\d,]+)\s*million",
        }
        for fname, pat in patterns.items():
            m = re.search(pat, text, re.I)
            if not m:
                continue
            val = float(m.group(1).replace(",", "")) * 0.1
            out = [f for f in out if f.field_name != fname]
            raw_val = float(m.group(1).replace(",", ""))
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
                reporting_basis=ReportingBasis.consolidated, field_name=fname,
                original_value=m.group(0), normalized_value=round(raw_val * 0.1, 4), currency="INR",
                unit="INR crore", source_value=raw_val, source_unit="INR million", scale_factor=0.1,
                source_page=1, source_table="press_release_highlights", source_text=m.group(0),
                confidence=0.95, confidence_method="prose_regex",
                validation_status=ValidationStatus.needs_review,
                extraction_engine="native_pymupdf_regex", model_version="regex-v1",
                section="quarterly_results", notes="From company Q2 FY27 press release"))

    by = {f.field_name: f for f in out}
    if "tax_expense" not in by and "current_tax" in by and "deferred_tax" in by:
        tax = by["current_tax"].normalized_value + by["deferred_tax"].normalized_value
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
            financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
            field_name="tax_expense", original_value="current tax + deferred tax",
            normalized_value=round(tax, 4), currency="INR", unit=by["current_tax"].unit,
            source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
            source_page=by["current_tax"].source_page, source_table="quarterly_results",
            source_text="Computed: current tax plus deferred tax", confidence=0.9,
            validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="quarterly_results", notes="Sum of current and deferred tax"))
        by["tax_expense"] = out[-1]
    if slug == "reliance" and "tax_expense" not in by and "pbt" in by and "pat" in by:
        tax = by["pbt"].normalized_value - by["pat"].normalized_value
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
            financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
            field_name="tax_expense", original_value="PBT - PAT",
            normalized_value=round(tax, 4), currency="INR", unit="INR crore",
            source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
            source_page=by["pbt"].source_page, source_table="quarterly_results",
            source_text="Computed: profit before tax minus profit after tax", confidence=0.85,
            validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="quarterly_results", notes="Tax computed as PBT minus PAT"))
        by["tax_expense"] = out[-1]
    if kind != "bank" and "total_income" not in by and "revenue" in by and "other_income" in by:
        val = by["revenue"].normalized_value + by["other_income"].normalized_value
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
            financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
            field_name="total_income", original_value="revenue + other income",
            normalized_value=round(val, 4), currency="INR", unit=by["revenue"].unit,
            source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
            source_page=by["revenue"].source_page, source_table="quarterly_results",
            source_text="Computed: revenue from operations plus other income", confidence=0.9,
            validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="quarterly_results", notes="Total income computed"))
        by["total_income"] = out[-1]
    if kind == "bank":
        ti = by.get("total_income")
        if ti is None or ti.normalized_value is None or ti.normalized_value <= 0:
            if "interest_income" in by and "other_income" in by:
                val = by["interest_income"].normalized_value + by["other_income"].normalized_value
                f = ExtractedField(
                    company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
                    financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
                    field_name="total_income", original_value="interest earned + other income",
                    normalized_value=round(val, 4), currency="INR", unit="INR crore",
                    source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
                    source_page=by["interest_income"].source_page, source_table="quarterly_results",
                    source_text="Computed: interest earned plus other income", confidence=0.9,
                    validation_status=ValidationStatus.arithmetic_ok,
                    extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                    section="quarterly_results", notes="Total income computed")
                out = [x for x in out if x.field_name != "total_income"] + [f]
                by["total_income"] = f
        if "total_income" in by and all(k in by for k in ("interest_expense", "operating_expenses")):
            prov = by["total_income"].normalized_value - by["interest_expense"].normalized_value - \
                by["operating_expenses"].normalized_value
            f = ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
                financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
                field_name="provisions", original_value="total income - interest expended - operating expenses",
                normalized_value=round(prov, 4), currency="INR", unit="INR crore",
                source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
                source_page=by["total_income"].source_page, source_table="quarterly_results",
                source_text="Computed residual provisions and contingencies", confidence=0.85,
                validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="quarterly_results", notes="Computed as residual; source lines are OCR-degraded")
            out = [x for x in out if x.field_name != "provisions"] + [f]
            by["provisions"] = f
        if "pat" in by and "tax_expense" in by:
            pbt = by["pat"].normalized_value + by["tax_expense"].normalized_value
            out = [x for x in out if x.field_name != "pbt"]
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
                financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
                field_name="pbt", original_value="PAT + tax expense",
                normalized_value=round(pbt, 4), currency="INR", unit="INR crore",
                source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
                source_page=by["pat"].source_page, source_table="quarterly_results",
                source_text="Computed: profit after tax plus tax expense", confidence=0.85,
                validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="quarterly_results", notes="Bank does not report a separate PBT line"))
    if kind != "bank" and "ebitda" not in by and all(
            k in by for k in ("pbt", "finance_costs", "depreciation_amortisation")):
        ebitda = by["pbt"].normalized_value + by["finance_costs"].normalized_value + by["depreciation_amortisation"].normalized_value
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
            financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
            field_name="ebitda", original_value="PBT + finance costs + depreciation",
            normalized_value=round(ebitda, 4), currency="INR", unit="INR crore",
            source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
            source_page=by["pbt"].source_page, source_table="quarterly_results",
            source_text="Computed: PBT + finance costs + D&A", confidence=0.85,
            validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="quarterly_results", notes="EBITDA computed transparently"))
    if kind == "bank" and "interest_income" in by and "interest_expense" in by:
        nii = by["interest_income"].normalized_value - by["interest_expense"].normalized_value
        out = [x for x in out if x.field_name != "net_interest_income"]
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="quarterly_results",
            financial_year=FIN_YEAR, report_period=PERIOD, reporting_basis=ReportingBasis.consolidated,
            field_name="net_interest_income", original_value="interest earned - interest expended",
            normalized_value=round(nii, 4), currency="INR", unit="INR crore",
            source_document=f"data/raw/{slug}/q2_fy2027_results.pdf",
            source_page=by["interest_income"].source_page, source_table="quarterly_results",
            source_text="Computed from interest earned minus interest expended", confidence=0.95,
            validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="quarterly_results", notes="NII calculated"))
    for f in out:
        f.company = meta.company or config.COMPANY_BY_SLUG[slug]["name"]
        f.financial_year = meta.financial_year
        f.report_period = meta.report_period
        f.source_document = meta.source_document
        f.source_sha256 = meta.sha256 or None
        f.run_id = config.RUN_ID
        if f.source_page is not None:
            f.source_page_label = labels.get(f.source_page) or str(f.source_page)
        if f.source_unit is None:
            f.source_unit = f.unit or "INR crore"
        if f.scale_factor is None:
            f.scale_factor = 1.0
        if f.is_derived or "computed" in (f.extraction_engine or ""):
            f.is_derived = True
            f.value_status = ValueStatus.derived
            if not f.formula:
                f.formula = f.original_value
            if not f.confidence_method:
                f.confidence_method = "derived_formula"
        elif not f.confidence_method:
            f.confidence_method = "label_regex+visual_row"
    return out


def extract_all_quarters() -> dict[str, list[dict]]:
    all_rows = {}
    for c in config.COMPANIES:
        slug = c["slug"]
        meta = periods.quarter_meta(slug)
        p = periods.source_path(meta)
        if not p.exists():
            print("missing", slug, p)
            continue
        fields = extract_quarter(slug, p)
        all_rows[slug] = [f.model_dump() for f in fields]
        out = config.STRUCTURED / slug / "quarterly_results.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "slug": slug, "company": meta.company, "document": meta.source_document,
            "financial_year": meta.financial_year, "report_period": meta.report_period,
            "basis": "consolidated", "sha256": meta.sha256, "run_id": config.RUN_ID,
            "fields": all_rows[slug],
        }, indent=1))
        print(f"{slug:12s} {len(fields):2d} fields  pages={sorted({f.source_page for f in fields})}")
    (config.STRUCTURED / "quarterly_fields.json").write_text(json.dumps(all_rows, indent=1))
    return all_rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        slug = sys.argv[1]
        for f in extract_quarter(slug, periods.source_path(periods.quarter_meta(slug))):
            print(f"{f.field_name:24s} {f.normalized_value!s:>14} p{f.source_page} {f.unit:12s} {f.original_value[:70]}")
    else:
        extract_all_quarters()
