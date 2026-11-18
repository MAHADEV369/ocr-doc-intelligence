"""Generate the company-wise financial tables from structured records."""
from __future__ import annotations

import json

import pandas as pd

from . import config


def _v(value, digits=0):
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{digits}f}"


def build():
    ms = pd.read_csv(config.DATA / "master_company_summary.csv")
    annual = json.loads((config.STRUCTURED / "annual_fields.json").read_text())
    L = ["# Company-wise extracted financial data (consolidated)", "",
         "All monetary values are normalised to **INR crore**. A dash means **not reported / not "
         "extractable**, never zero. Banks use total income as the revenue line; bank ratios are from "
         "the Q2 FY2026-27 presentations and retain their per-field reporting basis.", "",
         "## Annual report", "",
         "| Company | Revenue / total income | EBITDA | PAT | EPS (₹) | Total assets | Equity | CFO | Capex | FCF |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, r in ms.iterrows():
        L.append(f"| {r['company']} | {_v(r['revenue_fy26'])} | {_v(r['ebitda_fy26'])} | "
                 f"{_v(r['pat_fy26'])} | {_v(r['eps_fy26'], 2)} | {_v(r['total_assets_fy26'])} | "
                 f"{_v(r['equity_fy26'])} | {_v(r['cfo_fy26'])} | {_v(r['capex_fy26'])} | "
                 f"{_v(r['fcf_fy26'])} |")
    L += ["", "## Quarterly results", "",
          "| Company | Revenue / total income | PAT | EPS (₹) | NII | GNPA % | NNPA % | PCR % | CASA % | NIM % | CAR % |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, r in ms.iterrows():
        L.append(f"| {r['company']} | {_v(r['revenue_q2fy27'])} | {_v(r['pat_q2fy27'])} | "
                 f"{_v(r['eps_q2fy27'], 2)} | {_v(r['net_interest_income_q2fy27'])} | "
                 f"{_v(r['gnpa_pct_q2fy27'], 2)} | {_v(r['nnpa_pct_q2fy27'], 2)} | "
                 f"{_v(r['provision_coverage_pct_q2fy27'], 2)} | {_v(r['casa_pct_q2fy27'], 2)} | "
                 f"{_v(r['nim_pct_q2fy27'], 2)} | {_v(r['capital_adequacy_pct_q2fy27'], 2)} |")
    L += ["", "## Bank balance sheet", "",
          "| Company | Deposits | Advances | Borrowings | NII | Reporting basis |",
          "|---|---:|---:|---:|---:|---|"]
    for c in config.COMPANIES:
        if c["kind"] != "bank":
            continue
        rows = {r["field_name"]: r for r in annual.get(c["slug"], [])}
        def g(name):
            r = rows.get(name)
            return _v(r["normalized_value"]) if r else "—"
        L.append(f"| {c['name']} | {g('deposits')} | {g('advances')} | {g('borrowings')} | "
                 f"{g('net_interest_income')} | consolidated |")
    L += ["", "## Notes", "",
          "- HDFC Bank equity includes `Employees stock options / units outstanding` (4,545.11 crore).",
          "- HDFC and ICICI do not report a statutory PBT line; `profit_before_minority` is stored "
          "separately and marked derived.",
          "- Values printed in million/thousand/lakh are converted to crore; `source_value`, "
          "`source_unit` and `scale_factor` in the master dataset preserve the printed number."]
    (config.REPORTS / "company_financials.md").write_text("\n".join(L) + "\n")
    print("wrote", config.REPORTS / "company_financials.md")


if __name__ == "__main__":
    build()
