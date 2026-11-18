"""Validation and dataset export: CSV, Parquet, Excel, per-company packages."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import polars as pl

from . import config, periods, review
from .schemas import ExtractedField, ValueStatus
from .validation import write_report as write_validation_report

INCOME_FIELDS = ["revenue", "total_income", "ebitda", "depreciation_amortisation", "ebit",
                 "finance_costs", "pbt", "tax_expense", "pat", "eps_basic",
                 "interest_income", "interest_expense", "net_interest_income", "other_income",
                 "operating_expenses", "provisions", "profit_before_minority",
                 "net_profit_attributable"]
BS_FIELDS = ["total_assets", "total_liabilities", "equity", "borrowings", "cash", "investments",
             "receivables", "inventory", "deposits", "advances"]
CF_FIELDS = ["cfo", "cfi", "cff", "capex", "free_cash_flow"]
RATIO_FIELDS = ["net_interest_margin", "gnpa", "nnpa", "provision_coverage", "capital_adequacy",
                "casa", "average_deposits", "average_advances"]
ALL_FIELDS = INCOME_FIELDS + BS_FIELDS + CF_FIELDS + RATIO_FIELDS


def load_all() -> dict[str, list[dict]]:
    annual = json.load(open(config.STRUCTURED / "annual_fields.json"))
    quarterly = json.load(open(config.STRUCTURED / "quarterly_fields.json"))
    ratios = json.load(open(config.STRUCTURED / "bank_ratios.json"))
    out = {}
    for c in config.COMPANIES:
        slug = c["slug"]
        out[slug] = annual.get(slug, []) + quarterly.get(slug, []) + ratios.get(slug, [])
    return out


def validate(rows: list[dict], slug: str | None = None) -> dict:
    """Return separate provenance, structural and arithmetic checks.

    ``validation_total`` in the old dashboard counted every ``source_page_present``
    check together with the handful of real arithmetic checks. That made
    "428/428" look like an accuracy claim. The two families are now reported
    separately.
    """
    provenance = []
    accuracy = []
    unit_issues = []
    duplicate_issues = []
    seen = {}
    for r in rows:
        fname = r.get("field_name")
        provenance.append({
            "check": "source_page_present",
            "field": fname,
            "passed": r.get("source_page") is not None,
            "detail": f"{r.get('source_document')} p{r.get('source_page')}",
        })
        if r.get("source_page") is not None:
            provenance.append({
                "check": "source_text_present",
                "field": fname,
                "passed": bool((r.get("source_text") or "").strip()),
                "detail": (r.get("source_text") or "")[:120],
            })
        if r.get("source_sha256"):
            provenance.append({
                "check": "source_sha256_present",
                "field": fname,
                "passed": True,
                "detail": r["source_sha256"][:16] + "…",
            })
        key = (fname, r.get("financial_year"), r.get("document_type"))
        if key in seen:
            duplicate_issues.append({"field": fname, "period": r.get("financial_year"),
                                     "document_type": r.get("document_type")})
        seen[key] = r
        # Unit consistency: normalized value must equal source value x scale.
        unit = r.get("unit")
        source_value = r.get("source_value")
        scale = r.get("scale_factor")
        if unit in ("INR crore", "INR per share", "%") and source_value is not None and scale:
            expected = round(float(source_value) * float(scale), 4)
            actual = r.get("normalized_value")
            if actual is not None and abs(expected - float(actual)) > max(0.01, abs(expected) * 1e-6):
                unit_issues.append({
                    "field": fname, "unit": unit, "source_value": source_value,
                    "scale_factor": scale, "expected": expected, "stored": actual,
                })
        if r.get("value_status") == ValueStatus.derived.value and not (r.get("formula") or r.get("notes")):
            accuracy.append({"check": "derived_has_formula", "field": fname,
                             "passed": False, "detail": "derived record has no formula/notes"})
        if r.get("value_status") == ValueStatus.reported.value and r.get("source_page") is None:
            accuracy.append({"check": "reported_has_page", "field": fname,
                             "passed": False, "detail": "reported record has no source page"})

    # balance-sheet identity on annual data
    a = {r["field_name"]: r for r in rows if r.get("document_type") == "annual_report"}
    if "total_assets" in a and "total_equity_liabilities" in a:
        ta = a["total_assets"]["normalized_value"]
        tl = a["total_equity_liabilities"]["normalized_value"]
        same_row = a["total_assets"].get("source_text") == a["total_equity_liabilities"].get("source_text")
        diff = abs(ta - tl) / abs(ta) if ta else 1
        accuracy.append({"check": "balance_sheet_identity", "field": "total_assets",
                         "passed": bool(ta and diff < 0.005 and not same_row),
                         "detail": ("same source row; not independent" if same_row
                                    else f"difference {diff:.6%}")})
    if all(k in a for k in ("pbt", "tax_expense", "pat")):
        implied = a["pbt"]["normalized_value"] - a["tax_expense"]["normalized_value"]
        diff = abs(implied - a["pat"]["normalized_value"]) / abs(a["pbt"]["normalized_value"]) if a["pbt"]["normalized_value"] else 1
        accuracy.append({"check": "pbt_minus_tax_equals_pat", "field": "pat",
                         "passed": diff < 0.02, "detail": f"difference {diff:.4%}"})
    if "interest_income" in a and "interest_expense" in a and "net_interest_income" in a:
        implied = a["interest_income"]["normalized_value"] - a["interest_expense"]["normalized_value"]
        diff = abs(implied - a["net_interest_income"]["normalized_value"])
        accuracy.append({"check": "nii_identity", "field": "net_interest_income",
                         "passed": diff <= max(0.01, abs(implied) * 1e-6),
                         "detail": f"difference {diff:.4f}"})
    kind = config.COMPANY_BY_SLUG.get(slug, {}).get("kind", "industrial") if slug else "industrial"
    if kind == "bank":
        expected = ["interest_income", "interest_expense", "net_interest_income", "pat", "eps_basic",
                    "total_assets", "equity", "cash", "deposits", "advances"]
    else:
        expected = ["revenue", "total_income", "depreciation_amortisation", "finance_costs", "pbt",
                    "tax_expense", "pat", "eps_basic", "total_assets", "equity", "cfo"]
    missing = [f for f in expected if f not in a]
    all_checks = provenance + accuracy
    return {
        "checks": all_checks,
        "provenance_checks": len(provenance),
        "provenance_passed": sum(c["passed"] for c in provenance),
        "accuracy_checks": len(accuracy),
        "accuracy_passed": sum(c["passed"] for c in accuracy),
        "passed": sum(c["passed"] for c in provenance),
        "total": len(provenance),
        "missing_core_fields": sorted(set(missing)),
        "unit_issues": unit_issues,
        "duplicate_fields": duplicate_issues,
        "nulls_not_replaced_with_zero": True,
        "value_status_counts": {
            str(k): sum(1 for r in rows if str(r.get("value_status")) == str(k))
            for k in {r.get("value_status") for r in rows}
        },
    }


def _field_table(rows: list[dict], fields: list[str]) -> pd.DataFrame:
    out = []
    for f in fields:
        r = next((x for x in rows if x["field_name"] == f), None)
        if r:
            out.append({
                "field": f, "value": r["normalized_value"], "unit": r["unit"],
                "source_value": r.get("source_value"), "source_unit": r.get("source_unit"),
                "scale_factor": r.get("scale_factor"), "value_status": r.get("value_status"),
                "currency": r["currency"], "source_document": r["source_document"],
                "source_page": r["source_page"], "source_page_label": r.get("source_page_label"),
                "validation": r["validation_status"], "formula": r.get("formula", ""),
            })
    return pd.DataFrame(out)


def export_company(slug: str, rows: list[dict], master_df: pd.DataFrame) -> dict:
    c = config.COMPANY_BY_SLUG[slug]
    d = config.COMPANY_DATASETS / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "structured.json").write_text(json.dumps({
        "company": c["name"], "slug": slug, "sector": c["sector"],
        "generated": str(date.today()),
        "fields": rows,
    }, indent=1))
    # source manifest
    mpath = config.MANIFESTS / f"{slug}.json"
    if mpath.exists():
        (d / "source_manifest.json").write_text(mpath.read_text())
    # markdown
    md_parts = []
    for doc_type in ("annual_report", "quarterly_results", "investor_presentation"):
        p = config.PARSED / slug / doc_type / "document.md"
        if p.exists():
            md_parts.append(f"\n\n---\n\n# {doc_type}\n\n")
            text = p.read_text()
            # keep packages manageable: full annual report markdown is large but required
            md_parts.append(text)
    (d / "extracted.md").write_text("".join(md_parts))
    # statement CSVs
    inc = _field_table(rows, INCOME_FIELDS)
    bs = _field_table(rows, BS_FIELDS)
    cf = _field_table(rows, CF_FIELDS)
    q = pd.DataFrame([r for r in rows if r["financial_year"] == "FY2026-27"])
    inc.to_csv(d / "income_statement.csv", index=False)
    bs.to_csv(d / "balance_sheet.csv", index=False)
    cf.to_csv(d / "cash_flow.csv", index=False)
    q.to_csv(d / "quarterly_metrics.csv", index=False)
    # coverage: explicitly show fields that were not extracted, instead of
    # making them invisible simply because no row exists.
    present = {(r["field_name"], r.get("financial_year"), r.get("document_type")) for r in rows}
    coverage = []
    for field in ALL_FIELDS:
        for fy, dty in (("FY2025-26", "annual_report"), ("FY2026-27", "quarterly_results")):
            if (field, fy, dty) not in present:
                coverage.append({
                    "company": c["name"], "field": field, "financial_year": fy,
                    "document_type": dty, "normalized_value": None,
                    "value_status": "not_extracted",
                    "note": "not reported, not applicable, or not extractable; never silently zero",
                })
    pd.DataFrame(coverage).to_csv(d / "coverage.csv", index=False)
    # Excel workbook
    xlsx = d / "financial_summary.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        am = periods.annual_meta(slug)
        qm = periods.quarter_meta(slug)
        pd.DataFrame([{"company": c["name"], "sector": c["sector"],
                       "reporting_basis": "consolidated",
                       "annual_period": am.financial_year,
                       "quarterly_period": qm.financial_year}]).to_excel(w, sheet_name="Overview", index=False)
        inc.to_excel(w, sheet_name="Income Statement", index=False)
        bs.to_excel(w, sheet_name="Balance Sheet", index=False)
        cf.to_excel(w, sheet_name="Cash Flow", index=False)
        q.to_excel(w, sheet_name="Quarterly", index=False)
        pd.DataFrame(rows).to_excel(w, sheet_name="All Fields + Provenance", index=False)
        pd.DataFrame(coverage).to_excel(w, sheet_name="Coverage", index=False)
    # validation report
    vr = validate(rows, slug)
    (d / "validation_report.json").write_text(json.dumps(vr, indent=1))
    return {
        "slug": slug, "fields": len(rows),
        "validation_passed": vr["passed"], "validation_total": vr["total"],
        "provenance_passed": vr["provenance_passed"], "provenance_total": vr["provenance_checks"],
        "accuracy_passed": vr["accuracy_passed"], "accuracy_total": vr["accuracy_checks"],
        "unit_issues": len(vr["unit_issues"]),
        "missing": vr["missing_core_fields"],
    }


def export_all():
    allrows = review.apply_to_rows(load_all())
    flat = []
    for slug, rows in allrows.items():
        for r in rows:
            flat.append(r)
    schema_cols = [
        "record_id", "company", "document_type", "financial_year", "report_period", "reporting_basis",
        "field_name", "original_value", "normalized_value", "currency", "unit",
        "source_value", "source_unit", "scale_factor", "value_status", "is_derived", "formula",
        "source_document", "source_page", "source_page_label", "source_table", "source_text",
        "source_bbox", "source_sha256", "confidence", "confidence_method",
        "validation_status", "extraction_engine", "model_version", "section", "notes",
        "run_id", "extracted_at", "reviewer", "reviewed_at",
    ]
    df = pd.DataFrame(flat)
    for c in schema_cols:
        if c not in df:
            df[c] = None
    df = df[schema_cols]
    # Fill non-nullable defaults before contract validation.
    defaults = {
        "value_status": "reported",
        "is_derived": False,
        "formula": "",
        "confidence_method": "",
        "run_id": config.RUN_ID,
        "extracted_at": "",
        "reviewer": "",
        "reviewed_at": "",
    }
    for col, default in defaults.items():
        df[col] = df[col].where(pd.notna(df[col]), default)
    df = review.apply_to_df(df)
    # Validate with the pydantic contract (raises on contract violations).
    records = df.astype(object).where(pd.notna(df), None).to_dict(orient="records")
    parsed = [ExtractedField(**r) for r in records]
    if len(parsed) != len(df):
        raise ValueError("pydantic validation dropped rows")
    master_csv = config.DATA / "master_dataset.csv"
    master_parquet = config.DATA / "master_dataset.parquet"
    df.to_csv(master_csv, index=False)
    pl.from_pandas(df).write_parquet(master_parquet)
    # Excel master
    with pd.ExcelWriter(config.DATA / "master_dataset.xlsx", engine="openpyxl") as w:
        df.to_excel(w, sheet_name="All Fields", index=False)
        summary = df.groupby(["company", "financial_year"]).size().reset_index(name="fields")
        summary.to_excel(w, sheet_name="Coverage", index=False)
    write_validation_report(df)
    results = []
    for slug, rows in allrows.items():
        results.append(export_company(slug, rows, df))
    # One consolidated coverage matrix: every expected field appears, with an
    # explicit "not_extracted" status when no row was produced.
    cov_rows = []
    for c in config.COMPANIES:
        slug = c["slug"]
        for field in ALL_FIELDS:
            for fy, dty in (("FY2025-26", "annual_report"), ("FY2026-27", "quarterly_results")):
                row = next((r for r in allrows.get(slug, [])
                            if r["field_name"] == field and r["financial_year"] == fy
                            and r["document_type"] == dty), None)
                cov_rows.append({
                    "company": c["name"], "slug": slug, "field": field,
                    "financial_year": fy, "document_type": dty,
                    "normalized_value": row["normalized_value"] if row else None,
                    "unit": row["unit"] if row else None,
                    "value_status": row["value_status"] if row else "not_extracted",
                    "validation_status": row["validation_status"] if row else "not_applicable",
                    "source_page": row.get("source_page") if row else None,
                })
    pd.DataFrame(cov_rows).to_csv(config.DATA / "coverage_matrix.csv", index=False)
    (config.STRUCTURED / "export_summary.json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))
    print("master rows", len(df), "parquet", master_parquet,
          "coverage rows", len(cov_rows))
    return df


if __name__ == "__main__":
    export_all()
