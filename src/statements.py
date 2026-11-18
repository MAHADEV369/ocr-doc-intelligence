"""Financial statement locator and row-level extraction.

Page ranges were located by inspecting each annual report's consolidated
financial statements (headings cross-checked against the printed page index).
Every value keeps its PDF page and the exact source lines.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from . import config, periods
from .schemas import ExtractedField, ReportingBasis, ValidationStatus, ValueStatus
from .units import UnitInfo, detect_unit, is_unit_header

STATEMENT_PAGES = {
    "reliance": {"balance_sheet": [100], "profit_and_loss": [101], "cash_flow": [103]},
    "tcs": {"balance_sheet": [166], "profit_and_loss": [167], "cash_flow": [172, 173]},
    "infosys": {"balance_sheet": [285, 286], "profit_and_loss": [287, 288], "cash_flow": [294, 295]},
    "larsen": {"balance_sheet": [616, 617], "profit_and_loss": [618, 619], "cash_flow": [622, 623]},
    "itc": {"balance_sheet": [254], "profit_and_loss": [255], "cash_flow": [258, 259]},
    "sunpharma": {"balance_sheet": [240, 241], "profit_and_loss": [242, 243], "cash_flow": [245, 246]},
    "airtel": {"balance_sheet": [214, 215], "profit_and_loss": [214], "cash_flow": [216]},
    "icici": {"balance_sheet": [271], "profit_and_loss": [272], "cash_flow": [273, 274]},
    "hdfc": {"balance_sheet": [471], "profit_and_loss": [472], "cash_flow": [473, 474]},
    "tatamotors": {"balance_sheet": [268], "profit_and_loss": [269], "cash_flow": [270, 271]},
}

PREFIX_RE = re.compile(r"^(?:(?:\(?(?:[IVXLC]+|\d{1,2}|[a-z])[.)]?)\s+|(?:less|add)\s*[:\-]\s*)+", re.I)
TRAIL_RE = re.compile(r"\s*(?:\(contd\.?\)|\(continued\)|\[.*?\])\s*$", re.I)
NOTE_RE = re.compile(r"^[\(\d][\dA-Za-z,() /&\-]{0,18}$")
NUM_RE = re.compile(r"^\(?-?(?:[\d][\d,]*(?:\.\d+)?|\.\d+)\)?$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
STOPWORDS = {"the", "of", "to", "and", "in", "on", "for", "by", "with", "from", "under", "as", "per"}


def norm(s: str) -> str:
    s = s.replace("\ufb01", "fi").replace("\ufb02", "fl").replace("\ufb00", "ff")
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()


def clean_label(s: str) -> str:
    s = CTRL_RE.sub(" ", s)
    s = norm(s).strip()
    s = PREFIX_RE.sub("", s)
    s = TRAIL_RE.sub("", s)
    return s.strip(" .:")


def parse_number(tok: str) -> float | None:
    tok = tok.strip().replace("₹", "").replace("`", "").replace("H", "₹")
    if re.fullmatch(r"[0-9OoIl.,()\-]+", tok) and re.search(r"\d", tok):
        tok = tok.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    if tok in {"-", "–", "—", "Nil", "nil", "NIL"}:
        return 0.0
    neg = tok.startswith("(") and tok.endswith(")")
    tok = tok.strip("()").replace(",", "").replace("%", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", tok):
        return None
    v = float(tok)
    return -v if neg else v


def extract_numbers(line: str) -> list[float]:
    out = []
    for tok in re.findall(r"\(?-?[0-9OoIl][0-9OoIl,]*(?:\.[0-9OoIl]+)?\)?", line):
        digits = len(re.findall(r"\d", tok))
        if digits < 2 and "," not in tok and "." not in tok:
            continue
        v = parse_number(tok)
        if v is not None:
            out.append(v)
    return out


def unit_multiplier_to_crore(text: str) -> tuple[float, str]:
    """Backwards-compatible wrapper around :func:`src.units.detect_unit`."""
    info = detect_unit(text)
    return info.multiplier, info.source_unit


@dataclass
class Line:
    page: int
    text: str
    clean: str


def load_lines(path: Path, pages: list[int],
               default_unit: UnitInfo | None = None) -> tuple[list[Line], UnitInfo]:
    doc = fitz.open(path)
    raw: list[Line] = []
    unit_info = default_unit or UnitInfo()
    unit_found = False
    for p in pages:
        txt = doc[p - 1].get_text("text")
        if not unit_found:
            for line in txt.splitlines():
                if is_unit_header(line):
                    unit_info = detect_unit(line)
                    unit_found = True
                    break
        for r in txt.splitlines():
            s = norm(CTRL_RE.sub(" ", r))
            if s:
                raw.append(Line(p, s, clean_label(s).lower()))
    # merge wrapped label lines (no digits, continuation words / lowercase start)
    lines: list[Line] = []
    for ln in raw:
        if lines and not re.search(r"\d", ln.text) and len(ln.text) < 80:
            prev = lines[-1]
            if (not re.search(r"\d", prev.text) and len(prev.text) < 120
                    and (ln.text[:1].islower() or prev.text.split()[-1].lower() in STOPWORDS
                         or ln.text in ("Group", "Company", "Limited", "Account"))
                    and not prev.text.endswith((".", ":"))):
                prev.text = prev.text + " " + ln.text
                prev.clean = clean_label(prev.text).lower()
                continue
        lines.append(ln)
    return lines, unit_info


NIL_TOKENS = {"-", "\u2013", "\u2014", "nil", "NIL", "Nil", "n.a.", "N.A.", "NA"}


def is_nil_source(source: str, value: float | None = None) -> bool:
    """True when the row's numeric value is a printed dash/nil marker."""
    if value not in (None, 0, 0.0):
        return False
    tokens = re.split(r"[\s|]+", source or "")
    if not any(t in NIL_TOKENS for t in tokens):
        return False
    # A zero next to another non-zero number is a real zero, not nil.
    nums = re.findall(r"[1-9][\d,]*", source or "")
    return not nums


def is_note_ref(s: str) -> bool:
    if re.search(r"\d,\d{2,3}", s) or re.search(r"\d{4,}", s):
        return False
    if re.search(r"[OoIl]", s) and re.search(r"\d", s):
        return False
    if "." in s:
        return bool(re.search(r"[A-Za-z]", s))
    if not re.fullmatch(r"[\(\)\dA-Za-z., /&\-]+", s):
        return False
    nums = re.findall(r"\d+", s)
    if not nums or len(nums) > 8:
        return False
    limit = 30 if "." in s else 60
    return all(int(n) <= limit for n in nums)


def table_find(page, patterns: list[str]):
    hits = []
    try:
        tables = page.find_tables().tables
    except Exception:
        return hits
    for table in tables:
        try:
            rows = table.extract()
        except Exception:
            continue
        for row in rows:
            cells = [c or "" for c in row]
            label = clean_label(" ".join(cells[:2])).lower()
            if not label or not any(re.search(p, label) for p in patterns):
                continue
            nums = []
            for cell in cells[2:]:
                for part in str(cell).split("\n"):
                    part = part.strip()
                    if part and re.fullmatch(r"[\(\dOoIl,./%\-–— ]+", part):
                        nums.extend(extract_numbers(part))
            if nums:
                hits.append((label, nums, page.number + 1, " ".join(cells)[:250]))
    return hits


def find_rows(lines: list[Line], patterns: list[str], max_lookahead: int = 12,
              drop_note_values: bool = True):
    hits = []
    for idx, ln in enumerate(lines):
        if not ln.clean or len(ln.clean) > 240:
            continue
        matched = next((p for p in patterns if re.search(p, ln.clean)), None)
        if not matched:
            continue
        vals: list[float] = []
        src = [ln.text]
        same = extract_numbers(ln.text)
        if len(same) >= 2 and all(abs(x) < 10 for x in same):
            same = []  # equation tokens such as (1)+(2) in the label
        if re.search(r"\(\d{1,3}\)\s*[-+–]", ln.text):
            same = []  # equation references such as (12)-(13)
        # A label line may be "Revenue from operations 12 2,67,021 2,55,324".
        while len(same) >= 3 and abs(same[0]) < 100:
            same = same[1:]
        if len(same) == 2 and abs(same[0]) < 100 and abs(same[1]) > 1000 and (same[0] != int(same[0]) or abs(same[0]) < 50):
            same = same[1:]
        if len(same) >= 2:
            vals = same[:2]
        else:
            vals = same[:]
            sub_label_count = 0
            for j in range(idx + 1, min(idx + 1 + max_lookahead, len(lines))):
                nxt = lines[j]
                s = nxt.text
                if is_note_ref(s):
                    continue
                if re.fullmatch(r"\([^\d]{3,40}\)", s) or (s.startswith("(") and not re.search(r"\d", s) and len(s) < 45):
                    continue
                if re.fullmatch(r"[\s\-–—]+", s):
                    vals.append(0.0); src.append(s)
                    if len(vals) >= 4:
                        break
                    continue
                if NUM_RE.fullmatch(s) or re.fullmatch(r"[\d,]+\.\d+", s):
                    vals.append(parse_number(s)); src.append(s)
                    if len(vals) >= 4:
                        break
                    continue
                if re.fullmatch(r"[\s0-9OoIl,().%\-–—]+", s) and len(re.findall(r"\d", s)) >= 2:
                    vals.extend(extract_numbers(s)); src.append(s)
                    if len(vals) >= 4:
                        break
                    continue
                # Any alphabetic row label ends the numeric lookahead. The
                # previous version allowed short labels such as "Total" to
                # pass through and then collected the next row's numbers.
                short_sub_label = (
                    not vals
                    and sub_label_count < 2
                    and re.fullmatch(r"[A-Za-z][A-Za-z .&/-]{2,24}", s.strip())
                    and s.strip().lower() in {
                        "billed", "unbilled", "considered good", "considered doubtful",
                        "secured", "unsecured", "current", "non-current",
                        "related parties", "others", "gross", "net",
                    }
                )
                if short_sub_label:
                    sub_label_count += 1
                    continue
                if re.search(r"[a-zA-Z]{3,}", nxt.clean):
                    break
        while drop_note_values and len(vals) > 2 and 0 <= vals[0] < 30:
            vals = vals[1:]
        if len(vals) >= 2 and 0 < abs(vals[0]) < 100 and abs(vals[1]) > 1000:
            vals = vals[1:]
        if vals:
            hits.append((ln.text, vals[:4], ln.page, " | ".join(src)))
    return hits


def visual_rows(page) -> list[tuple[str, list[float], str]]:
    """Group text spans into visual rows and return (label, numbers, raw row text)."""
    spans = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if t:
                    spans.append((span["bbox"], t))
    if not spans:
        return []
    spans.sort(key=lambda z: ((z[0][1] + z[0][3]) / 2, z[0][0]))
    rows = []
    for bbox, text in spans:
        yc = (bbox[1] + bbox[3]) / 2
        placed = False
        for row in rows:
            if abs(row["y"] - yc) <= 4.5:
                row["spans"].append((bbox, text)); row["y"] = (row["y"] + yc) / 2; placed = True
                break
        if not placed:
            rows.append({"y": yc, "spans": [(bbox, text)]})
    out = []
    for row in sorted(rows, key=lambda r: r["y"]):
        row["spans"].sort(key=lambda z: z[0][0])
        label_parts, nums = [], []
        for bbox, text in row["spans"]:
            raw = text.replace("₹", "").strip()
            if re.fullmatch(r"[\s\d,().%\-–—]+", raw) and re.search(r"\d", raw):
                ns = extract_numbers(raw)
                if ns:
                    nums.extend(ns)
                    continue
            label_parts.append(text)
        label = clean_label(" ".join(label_parts)).lower()
        raw = " ".join(t for _, t in row["spans"])
        if label:
            out.append((label, nums, raw))
    return out


def visual_find(page, patterns: list[str]):
    hits = []
    for label, nums, raw in visual_rows(page):
        if any(re.search(p, label) for p in patterns):
            hits.append((label, nums, page.number + 1, raw))
    return hits


PATTERNS = {
    "revenue": [r"^revenue from operations?(?: \(net\))?$", r"^net revenue$", r"^revenue$",
                r"^total revenue from operations$"],
    "total_income": [r"^total income$", r"^total income \(?i\s*\+\s*ii\)?$", r"^total income \(i\+ii\)$", r"^total revenue$"],
    "depreciation_amortisation": [r"^depreciation(?:,| and| /| &)? ?(?:amorti[sz]ation|depletion|impairment).*"],
    "finance_costs": [r"^finance costs?$", r"^interest expense$", r"^finance cost of financial services.*"],
    "pbt": [r"^profit before tax$", r"^profit before tax \(.*\)$", r"^profit before exceptional items and tax.*",
            r"^profit before share of profit.*tax$", r"^profit.*before tax.*$"],
    "tax_expense": [r"^total tax expense$", r"^total tax expense \(.*\)$", r"^total tax$",
                     r"^tax expenses?$"],
    "pat": [r"^profit for the year$", r"^profit for the year/period.*$", r"^profit.*for the (?:period|quarter|year).*$", r"^profit for the year \(.*\)$",
            r"^profit for the year before non-controlling interests.*$",
            r"^net profit after tax$", r"^profit after tax$", r"^net profit$",
            r"^consolidated net profit.*attributable to the group$",
            r"^consolidated profit.*attributable to the group$",
            r"^profit for the year attributable to owners of the parent.*$"],
    "eps_basic": [r"^basic\b", r"^basic earnings per.*", r"^earnings per equity share.*basic.*",
                  r"^earnings per share.*basic.*"],
    "total_assets": [r"^total assets$", r"^total$"],
    "total_equity_liabilities": [r"^total equity and liabilities$", r"^total capital and liabilities$",
                                 r"^total liabilities and equity$"],
    "equity": [r"^total equity$", r"^total shareholders'? funds$", r"^total equity attributable to.*"],
    "borrowings": [r"^borrowings$", r"^total borrowings$", r"^debt$"],
    "cash": [r"^cash and cash equivalents?$", r"^cash and bank balances$",
             r"^cash and balances with reserve bank of india$", r"^cash and balances with rbi$"],
    "investments": [r"^investments?$", r"^total investments$"],
    "receivables": [r"^trade receivables?$", r"^debtors$"],
    "inventory": [r"^inventories$", r"^inventory$"],
    "cfo": [r"^net cash (?:flows?|flow)? ?(?:from|generated from|used in)/?\(?used in\)? operating activities.*",
            r"^net cash.*operating activities.*", r"^cash flow from/?\(?used in\)? operating activities.*"],
    "cfi": [r"^net cash (?:flows?|flow)? ?(?:from|used in)/?\(?used in\)? investing activities.*",
            r"^net cash.*investing activities.*"],
    "cff": [r"^net cash (?:flows?|flow)? ?(?:from|used in|generated from)/?\(?used in\)? financing activities.*",
            r"^net cash.*financing activities.*"],
    "capex": [r"^purchase of (?:property, plant and equipment|pp&e|fixed assets).*",
              r"^payments? for (?:purchase of )?property.*", r"^capital expenditure.*",
              r"^expenditure (?:for|on) property.*", r"^purchase of fixed assets$"],
    "interest_income": [r"^interest earned$", r"^interest income$"],
    "interest_expense": [r"^interest expended$", r"^interest expense$"],
    "other_income": [r"^other income$"],
    "operating_expenses": [r"^operating expenses$"],
    "provisions": [r"^provisions and contingencies.*", r"^provisions$"],
    "total_expenditure": [r"^total expenditure$"],
    "deposits": [r"^deposits$"],
    "advances": [r"^advances$"],
    "capital": [r"^capital$"],
    "reserves_surplus": [r"^reserves and surplus$"],
    "minority_interest": [r"^minority interest$"],
    "esop": [r"^employees?\s+stock\s+options?\s*(?:/|and)?\s*units?\s+outstanding$",
             r"^employees?\s+stock\s+options?\s+outstanding$"],
    "net_profit_attributable": [r"^consolidated (?:net )?profit.*attributable to the group.*",
                                 r"^net profit for the year.*minority interest.*"],
    "current_tax": [r"^current tax$"],
    "deferred_tax": [r"^deferred tax$"],
    "equity_share_capital": [r"^equity share capital$", r"^share capital$"],
    "other_equity": [r"^other equity$"],
    "nci": [r"^non-controlling interests?.*"],
}

PREFERRED = {
    "revenue": ["total revenue from operations", "revenue from operations", "gross revenue", "revenue"],
    "net_profit_attributable": ["consolidated profit", "consolidated net profit"],
    "equity": ["total equity", "total shareholders", "total equity attributable"],
    "finance_costs": ["finance costs", "finance cost", "interest expense"],
    "pat": ["profit for the year before non-controlling interests", "profit for the year", "net profit after tax", "profit after tax", "consolidated net profit",
            "consolidated profit", "net profit", "profit for the year before"],
    "total_assets": ["total assets", "total"],
    "total_equity_liabilities": ["total equity and liabilities", "total capital and liabilities", "total"],
    "cfo": ["net cash from operating", "net cash generated from operating", "net cash flows from operating",
            "net cash flow from", "net cash"],
    "tax_expense": ["total tax expense", "tax expense"],
    "pbt": ["profit before tax", "profit before exceptional"],
}


def pick(hits, field):
    if not hits:
        return None
    prefs = PREFERRED.get(field, [])
    for pref in prefs:
        for h in hits:
            if clean_label(h[0]).lower() == pref:
                return h
    for pref in prefs:
        for h in hits:
            if clean_label(h[0]).lower().startswith(pref):
                return h
    return hits[0]


def page_labels(path: Path) -> dict[int, str]:
    """PDF page index -> printed page label, when the PDF provides one."""
    try:
        doc = fitz.open(path)
        labels = {i + 1: (doc[i].get_label() or "") for i in range(doc.page_count)}
        doc.close()
        return labels
    except Exception:
        return {}


def document_unit(path: Path, pages: dict[str, list[int]]) -> UnitInfo:
    """Find the document's printed unit once and reuse it on pages that omit it."""
    try:
        doc = fitz.open(path)
        for section in ("balance_sheet", "profit_and_loss", "cash_flow"):
            for page_no in pages.get(section, []) or []:
                for line in doc[page_no - 1].get_text("text").splitlines():
                    if is_unit_header(line):
                        info = detect_unit(line)
                        if not info.is_canonical:
                            doc.close()
                            return info
        doc.close()
    except Exception:
        pass
    return UnitInfo()


def discover_statement_pages(path: Path) -> dict[str, list[int]]:
    """Locate consolidated statements from the PDF outline, then headings.

    The curated ``STATEMENT_PAGES`` map remains an override for the benchmark
    corpus; this function makes a new filing usable without editing code.
    """
    doc = fitz.open(path)
    found: dict[str, list[int]] = {}
    toc = []
    try:
        toc = doc.get_toc()
    except Exception:
        pass
    patterns = {
        "balance_sheet": re.compile(r"consolidated\s+balance\s+sheet", re.I),
        "profit_and_loss": re.compile(r"consolidated\s+(?:statement\s+of\s+)?profit\s+and\s+loss", re.I),
        "cash_flow": re.compile(r"consolidated\s+(?:statement\s+of\s+)?cash\s+flow", re.I),
    }
    for _level, title, page in toc:
        for name, pat in patterns.items():
            if name not in found and pat.search(title or "") and page and 1 <= page <= doc.page_count:
                found[name] = [page]
    if not found:
        for i in range(doc.page_count):
            text = " ".join(doc[i].get_text("text").splitlines()[:12]).lower()
            for name, pat in patterns.items():
                if name not in found and pat.search(text):
                    found[name] = [i + 1]
    doc.close()
    return found


def extract_annual(slug: str, path: Path) -> list[ExtractedField]:
    kind = config.COMPANY_BY_SLUG[slug]["kind"]
    pages = STATEMENT_PAGES.get(slug) or discover_statement_pages(path)
    out: list[ExtractedField] = []
    basis = ReportingBasis.consolidated
    meta = periods.annual_meta(slug)
    labels = page_labels(path)
    doc_unit = document_unit(path, pages)
    fname_map = {
        "revenue": "profit_and_loss", "total_income": "profit_and_loss",
        "depreciation_amortisation": "profit_and_loss", "finance_costs": "profit_and_loss",
        "pbt": "profit_and_loss", "tax_expense": "profit_and_loss", "pat": "profit_and_loss",
        "eps_basic": "profit_and_loss", "total_assets": "balance_sheet",
        "total_equity_liabilities": "balance_sheet", "equity": "balance_sheet",
        "borrowings": "balance_sheet", "cash": "balance_sheet", "investments": "balance_sheet",
        "receivables": "balance_sheet", "inventory": "balance_sheet", "cfo": "cash_flow",
        "cfi": "cash_flow", "cff": "cash_flow", "capex": "cash_flow",
        "interest_income": "profit_and_loss", "interest_expense": "profit_and_loss",
        "other_income": "profit_and_loss", "operating_expenses": "profit_and_loss",
        "provisions": "profit_and_loss", "deposits": "balance_sheet", "advances": "balance_sheet",
        "capital": "balance_sheet", "reserves_surplus": "balance_sheet",
        "minority_interest": "balance_sheet", "esop": "balance_sheet",
        "net_profit_attributable": "profit_and_loss", "total_expenditure": "profit_and_loss",
        "current_tax": "profit_and_loss", "deferred_tax": "profit_and_loss",
        "equity_share_capital": "balance_sheet", "other_equity": "balance_sheet", "nci": "balance_sheet",
    }
    allowed = {
        "profit_and_loss": {"revenue", "total_income", "depreciation_amortisation", "finance_costs", "pbt",
                            "tax_expense", "pat", "eps_basic", "interest_income", "interest_expense",
                            "other_income", "operating_expenses", "provisions", "net_profit_attributable",
                            "total_expenditure", "current_tax", "deferred_tax"},
        "balance_sheet": {"total_assets", "total_equity_liabilities", "equity", "borrowings", "cash",
                          "investments", "receivables", "inventory", "deposits", "advances", "capital",
                          "reserves_surplus", "minority_interest", "esop", "equity_share_capital",
                          "other_equity", "nci"},
        "cash_flow": {"cfo", "cfi", "cff", "capex", "pat"},
    }
    for section, plist in pages.items():
        if not plist or not plist[0]:
            continue
        lines, unit_info = load_lines(path, plist, default_unit=doc_unit)
        for fname, sec in fname_map.items():
            if sec != section or fname not in allowed[section]:
                continue
            hits = find_rows(lines, PATTERNS[fname], drop_note_values=(fname != "eps_basic"))
            if not hits:
                continue
            if fname in {"borrowings", "investments"} and len(hits) > 1 and not any(
                    "total" in clean_label(h[0]).lower() for h in hits):
                vals = [sum(h[1][i] for h in hits if len(h[1]) > i) for i in range(2)]
                label = " + ".join(clean_label(h[0]) for h in hits)
                page = hits[0][2]
                src = " || ".join(h[3] for h in hits)
                raw = f"{label}: " + " / ".join(f"{clean_label(h[0])} {h[1]}" for h in hits)
            else:
                if fname in {"receivables", "inventory", "cash"} and len(hits) > 1:
                    h = max(hits, key=lambda z: abs(z[1][0]))
                else:
                    h = pick(hits, fname)
                label, vals, page, src = h
                raw = src
            if not vals:
                continue
            if fname == "eps_basic" and len(vals) >= 2 and 0 < abs(vals[0]) < 10 and abs(vals[1]) > 10:
                vals = vals[1:]
            multiplier = 1.0 if fname == "eps_basic" else unit_info.multiplier
            unit = "INR per share" if fname == "eps_basic" else unit_info.canonical_unit
            source_unit = "INR per share" if fname == "eps_basic" else unit_info.source_unit
            conf = 0.92 if len(vals) >= 2 else 0.7
            vstatus = (ValueStatus.nil if is_nil_source(src, vals[0])
                       else ValueStatus.reported)
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                reporting_basis=basis, field_name=fname, original_value=raw,
                normalized_value=round(vals[0] * multiplier, 4), currency="INR",
                unit=unit, source_value=vals[0], source_unit=source_unit,
                scale_factor=multiplier,
                source_page=page, source_table=section, source_text=src, confidence=conf,
                value_status=vstatus, confidence_method="label_regex+visual_row",
                validation_status=ValidationStatus.needs_review, extraction_engine="native_pymupdf",
                model_version="PyMuPDF 1.27.2.2", section=section,
                notes=f"prior_year_value={round(vals[1] * multiplier, 4) if len(vals) > 1 else None}",
            ))
    by = {f.field_name: f for f in out}
    if "tax_expense" not in by and "current_tax" in by and "deferred_tax" in by:
        tax = by["current_tax"].normalized_value + by["deferred_tax"].normalized_value
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
            financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
            reporting_basis=basis, field_name="tax_expense", original_value="current tax + deferred tax",
            normalized_value=round(tax, 4), currency="INR", unit=by["current_tax"].unit,
            source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
            source_page=by["current_tax"].source_page, source_table="profit_and_loss",
            source_text="Computed: current tax plus deferred tax (no total tax row reported)",
            confidence=0.9, validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="profit_and_loss", notes="Sum of reported current and deferred tax"))
        by["tax_expense"] = out[-1]
    if kind != "bank" and "total_income" not in by and "revenue" in by and "other_income" in by:
        ti = by["revenue"].normalized_value + by["other_income"].normalized_value
        f = ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
            financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
            reporting_basis=basis, field_name="total_income", original_value="revenue + other income",
            normalized_value=round(ti, 4), currency="INR", unit=by["revenue"].unit,
            source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
            source_page=by["revenue"].source_page, source_table="profit_and_loss",
            source_text="Computed: revenue from operations plus other income",
            confidence=0.9, validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="profit_and_loss", notes="Total income computed")
        out.append(f); by["total_income"] = f
    # industrial equity fallback: share capital + other equity + NCI
    if kind != "bank" and "equity" not in by and "equity_share_capital" in by and "other_equity" in by:
        eq = by["equity_share_capital"].normalized_value + by["other_equity"].normalized_value
        src_text = "equity share capital + other equity"
        if "nci" in by:
            eq += by["nci"].normalized_value
            src_text += " + non-controlling interests"
        f = ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
            financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
            reporting_basis=basis, field_name="equity", original_value=src_text,
            normalized_value=round(eq, 4), currency="INR", unit=by["other_equity"].unit,
            source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
            source_page=by["other_equity"].source_page, source_table="balance_sheet",
            source_text="Computed from equity share capital, other equity and NCI where disclosed",
            confidence=0.9, validation_status=ValidationStatus.arithmetic_ok,
            extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
            section="balance_sheet", notes="Report does not present a single Total Equity row")
        out.append(f); by["equity"] = f
    # fallbacks for generic "Total" row
    if "total_assets" not in by and "total_equity_liabilities" in by:
        src = by["total_equity_liabilities"]
        by["total_assets"] = src.model_copy(update={
            "field_name": "total_assets",
            "value_status": ValueStatus.derived,
            "is_derived": True,
            "notes": "Copied from total equity and liabilities; not an independent total-assets reading",
        })
        out.append(by["total_assets"])
    if "total_assets" not in by:
        lines, _fallback_unit = load_lines(path, pages.get("balance_sheet", []), default_unit=doc_unit)
        totals = [h for h in find_rows(lines, [r"^total$"]) if len(h[1]) >= 2]
        if totals:
            h = totals[-1]
            f = ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="total_assets", original_value=h[3],
                normalized_value=round(h[1][0] * _fallback_unit.multiplier, 4), currency="INR",
                unit=_fallback_unit.canonical_unit, source_value=h[1][0],
                source_unit=_fallback_unit.source_unit, scale_factor=_fallback_unit.multiplier,
                source_page=h[2],
                source_table="balance_sheet", source_text=h[3], confidence=0.75,
                validation_status=ValidationStatus.needs_review, extraction_engine="native_pymupdf",
                model_version="PyMuPDF 1.27.2.2", section="balance_sheet",
                notes="Generic Total row on balance sheet")
            out.append(f); by["total_assets"] = f
    if "total_equity_liabilities" not in by and "total_assets" in by:
        f = by["total_assets"].model_copy(update={
            "field_name": "total_equity_liabilities",
            "value_status": ValueStatus.derived,
            "is_derived": True,
            "notes": "Copied from total assets; not an independent liabilities-and-equity reading",
        })
        out.append(f); by["total_equity_liabilities"] = f

    # ---- derived fields ----
    if kind == "bank":
        if "interest_income" in by and "interest_expense" in by:
            nii = by["interest_income"].normalized_value - by["interest_expense"].normalized_value
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="net_interest_income",
                original_value=f"interest earned - interest expended = {by['interest_income'].normalized_value} - {by['interest_expense'].normalized_value}",
                normalized_value=round(nii, 4), currency="INR", unit="INR crore",
                source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
                source_page=by["interest_income"].source_page, source_table="profit_and_loss",
                source_text="Computed from interest earned minus interest expended",
                confidence=0.95, validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="profit_and_loss", notes="NII calculated; bank does not report a single NII row"))
        if "total_income" not in by and "interest_income" in by and "other_income" in by:
            ti = by["interest_income"].normalized_value + by["other_income"].normalized_value
            f = ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="total_income", original_value="interest earned + other income",
                normalized_value=round(ti, 4), currency="INR", unit="INR crore",
                source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
                source_page=by["interest_income"].source_page, source_table="profit_and_loss",
                source_text="Computed: interest earned plus other income",
                confidence=0.9, validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="profit_and_loss", notes="Total income computed because report labels the row simply Total")
            out.append(f); by["total_income"] = f
        if "total_expenditure" not in by and all(k in by for k in ("interest_expense", "operating_expenses", "provisions")):
            te = sum(by[k].normalized_value for k in ("interest_expense", "operating_expenses", "provisions"))
            f = ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="total_expenditure", original_value="interest expended + operating expenses + provisions",
                normalized_value=round(te, 4), currency="INR", unit="INR crore",
                source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
                source_page=by["operating_expenses"].source_page, source_table="profit_and_loss",
                source_text="Computed from reported expenditure components",
                confidence=0.9, validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="profit_and_loss", notes="Total expenditure computed")
            out.append(f); by["total_expenditure"] = f
        if "total_income" in by and "total_expenditure" in by:
            # For a bank, total expenditure includes provisions and tax. The
            # resulting figure is *not* PBT; it is profit after tax and before
            # minority interest / associates. Naming it PBT would silently mix
            # it with industrial-company PBT.
            pbm = by["total_income"].normalized_value - by["total_expenditure"].normalized_value
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                reporting_basis=basis, field_name="profit_before_minority",
                original_value="total income - total expenditure",
                normalized_value=round(pbm, 4), currency="INR", unit="INR crore",
                source_page=by["total_income"].source_page, source_table="profit_and_loss",
                source_text="Computed: total income less total expenditure",
                confidence=0.9, validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="profit_and_loss", value_status=ValueStatus.derived, is_derived=True,
                formula="profit_before_minority = total_income - total_expenditure",
                notes="Bank P&L does not report a separate PBT line; this is profit after tax "
                      "and before minority interest/associates, as labelled in the source."))
        parts = [by.get("capital"), by.get("esop"), by.get("reserves_surplus"), by.get("minority_interest")]
        parts = [p for p in parts if p is not None]
        if parts:
            eq = sum(p.normalized_value for p in parts)
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="equity",
                original_value=" + ".join(p.field_name for p in parts),
                normalized_value=round(eq, 4), currency="INR", unit="INR crore",
                source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
                source_page=parts[-1].source_page, source_table="balance_sheet",
                source_text="Computed from capital, ESOP outstanding, reserves & surplus and minority interest",
                confidence=0.85, validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="balance_sheet", notes="Consolidated equity including minority interest"))
        if "net_profit_attributable" in by:
            out.append(by["net_profit_attributable"].model_copy(update={"field_name": "pat"}))
    else:
        if all(k in by for k in ("pbt", "finance_costs", "depreciation_amortisation")):
            ebitda = by["pbt"].normalized_value + by["finance_costs"].normalized_value + by["depreciation_amortisation"].normalized_value
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="ebitda", original_value="PBT + finance costs + depreciation & amortisation",
                normalized_value=round(ebitda, 4), currency="INR", unit="INR crore",
                source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
                source_page=by["pbt"].source_page, source_table="profit_and_loss",
                source_text="Transparent calculation from reported PBT, finance costs and D&A",
                confidence=0.85, validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="profit_and_loss", notes="EBITDA = PBT + finance costs + D&A; includes other income"))
        if all(k in by for k in ("pbt", "finance_costs")):
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="ebit", original_value="PBT + finance costs",
                normalized_value=round(by["pbt"].normalized_value + by["finance_costs"].normalized_value, 4),
                currency="INR", unit="INR crore", source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
                source_page=by["pbt"].source_page, source_table="profit_and_loss",
                source_text="Computed: PBT + finance costs", confidence=0.85,
                validation_status=ValidationStatus.arithmetic_ok, extraction_engine="native_pymupdf+computed",
                model_version="PyMuPDF 1.27.2.2", section="profit_and_loss", notes="EBIT = PBT + finance costs"))
        if all(k in by for k in ("cfo", "capex")):
            out.append(ExtractedField(
                company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
                financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
                reporting_basis=basis, field_name="free_cash_flow", original_value="CFO - capex (purchase of PPE)",
                normalized_value=round(by["cfo"].normalized_value - abs(by["capex"].normalized_value), 4),
                currency="INR", unit="INR crore", source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
                source_page=by["cfo"].source_page, source_table="cash_flow",
                source_text="Computed: net operating cash flow minus capital expenditure",
                confidence=0.8, validation_status=ValidationStatus.arithmetic_ok,
                extraction_engine="native_pymupdf+computed", model_version="PyMuPDF 1.27.2.2",
                section="cash_flow", notes="Capex approximated by purchase of property, plant and equipment line"))
    # dedupe by field name, keeping the last (derived/preferred) record
    dedup: dict[str, ExtractedField] = {}
    for f in out:
        dedup[f.field_name] = f
    out = list(dedup.values())
    # total liabilities
    by = {f.field_name: f for f in out}
    if "total_assets" in by and "equity" in by:
        out.append(ExtractedField(
            company=config.COMPANY_BY_SLUG[slug]["name"], document_type="annual_report",
            financial_year="FY2025-26", report_period="Year ended 31 Mar 2026",
            reporting_basis=basis, field_name="total_liabilities", original_value="total_assets - equity",
            normalized_value=round(by["total_assets"].normalized_value - by["equity"].normalized_value, 4),
            currency="INR", unit="INR crore", source_document=f"data/raw/{slug}/annual_report_fy2026.pdf",
            source_page=by["total_assets"].source_page, source_table="balance_sheet",
            source_text="Computed using the balance-sheet identity", confidence=0.85,
            validation_status=ValidationStatus.arithmetic_ok, extraction_engine="native_pymupdf+computed",
            model_version="PyMuPDF 1.27.2.2", section="balance_sheet",
            value_status=ValueStatus.derived, is_derived=True,
            formula="total_liabilities = total_assets - equity",
            notes="Derived plug: total assets minus total equity; not an independently reported total"))
    # ---- arithmetic validation ----
    by = {f.field_name: f for f in out}
    if "total_assets" in by and "total_equity_liabilities" in by:
        ta, tl = by["total_assets"].normalized_value, by["total_equity_liabilities"].normalized_value
        same_row = by["total_assets"].source_text == by["total_equity_liabilities"].source_text
        if ta and abs(ta - tl) / abs(ta) < 0.005 and not same_row:
            by["total_assets"].validation_status = ValidationStatus.verified
            by["total_equity_liabilities"].validation_status = ValidationStatus.verified
        elif same_row:
            for k in ("total_assets", "total_equity_liabilities"):
                if by[k].validation_status == ValidationStatus.verified:
                    by[k].validation_status = ValidationStatus.needs_review
                by[k].notes = (by[k].notes + " | same source row: balance-sheet identity is not independent").strip(" |")
    if "pbt" in by and "tax_expense" in by and "pat" in by:
        diff = abs((by["pbt"].normalized_value - by["tax_expense"].normalized_value) - by["pat"].normalized_value)
        if by["pbt"].normalized_value and diff / abs(by["pbt"].normalized_value) < 0.02:
            for k in ("pbt", "tax_expense", "pat"):
                by[k].validation_status = ValidationStatus.verified

    # ---- fill document metadata and provenance consistently ----
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
        elif f.value_status == ValueStatus.reported and not f.confidence_method:
            f.confidence_method = "label_regex+visual_row"
    return out


def extract_all_annual() -> dict[str, list[dict]]:
    all_rows: dict[str, list[dict]] = {}
    for c in config.COMPANIES:
        slug = c["slug"]
        meta = periods.annual_meta(slug)
        p = periods.source_path(meta)
        if not p.exists():
            print("missing", slug, p)
            continue
        fields = extract_annual(slug, p)
        all_rows[slug] = [f.model_dump() for f in fields]
        out = config.STRUCTURED / slug / "annual_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "slug": slug, "company": meta.company, "document": meta.source_document,
            "financial_year": meta.financial_year, "report_period": meta.report_period,
            "basis": "consolidated", "sha256": meta.sha256, "run_id": config.RUN_ID,
            "fields": all_rows[slug],
        }, indent=1))
        print(f"{slug:12s} {len(fields):3d} fields")
    (config.STRUCTURED / "annual_fields.json").write_text(json.dumps(all_rows, indent=1))
    return all_rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        slug = sys.argv[1]
        p = periods.source_path(periods.annual_meta(slug))
        for f in extract_annual(slug, p):
            print(f"{f.section:14s} {f.field_name:26s} {f.normalized_value!s:>16} p{f.source_page}  {f.original_value[:70]}")
    else:
        extract_all_annual()
