"""One-row-per-company summary across annual, quarterly and bank-ratio datasets."""
from __future__ import annotations

import json

import pandas as pd

from . import config, periods


def build():
    annual = json.loads((config.STRUCTURED / "annual_fields.json").read_text())
    quarterly = json.loads((config.STRUCTURED / "quarterly_fields.json").read_text())
    ratios = json.loads((config.STRUCTURED / "bank_ratios.json").read_text())
    rows = []
    for c in config.COMPANIES:
        slug = c["slug"]
        am = periods.annual_meta(slug)
        qm = periods.quarter_meta(slug)
        a = {x["field_name"]: x["normalized_value"] for x in annual.get(slug, [])}
        q = {x["field_name"]: x["normalized_value"] for x in quarterly.get(slug, [])}
        r = {x["field_name"]: x["normalized_value"] for x in ratios.get(slug, [])}
        rows.append({
            "company": c["name"], "slug": slug, "sector": c["sector"], "type": c["kind"],
            "annual_period": am.financial_year, "quarterly_period": qm.financial_year,
            "basis": "consolidated",
            "revenue_fy26": a.get("revenue", a.get("total_income")),
            "ebitda_fy26": a.get("ebitda"),
            "pat_fy26": a.get("pat"),
            "eps_fy26": a.get("eps_basic"),
            "total_assets_fy26": a.get("total_assets"),
            "equity_fy26": a.get("equity"),
            "borrowings_fy26": a.get("borrowings"),
            "cash_fy26": a.get("cash"),
            "cfo_fy26": a.get("cfo"),
            "capex_fy26": a.get("capex"),
            "fcf_fy26": a.get("free_cash_flow"),
            "deposits_fy26": a.get("deposits"),
            "advances_fy26": a.get("advances"),
            "net_interest_income_fy26": a.get("net_interest_income"),
            "revenue_q2fy27": q.get("revenue", q.get("total_income")),
            "net_interest_income_q2fy27": q.get("net_interest_income"),
            "pat_q2fy27": q.get("pat"),
            "eps_q2fy27": q.get("eps_basic"),
            "gnpa_pct_q2fy27": r.get("gnpa"),
            "nnpa_pct_q2fy27": r.get("nnpa"),
            "provision_coverage_pct_q2fy27": r.get("provision_coverage"),
            "casa_pct_q2fy27": r.get("casa"),
            "nim_pct_q2fy27": r.get("net_interest_margin"),
            "capital_adequacy_pct_q2fy27": r.get("capital_adequacy"),
            "source_annual": am.source_document,
            "source_quarterly": qm.source_document,
        })
    df = pd.DataFrame(rows)
    df.to_csv(config.DATA / "master_company_summary.csv", index=False)
    with pd.ExcelWriter(config.DATA / "master_company_summary.xlsx", engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Company summary", index=False)
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    build()
