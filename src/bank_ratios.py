"""Bank-specific ratios and balance-sheet metrics.

Values were read from the Q2 FY2026-27 investor presentations. Each record
keeps the page and the exact phrase/chart label it was read from. The
presentations label HDFC Bank figures as standalone; ICICI capital adequacy
is the consolidated ratio (slide 57), other ICICI ratios are the bank's
reported standalone/consolidated key ratios as stated on the slide.
"""
from __future__ import annotations

import json

from . import config, periods
from .schemas import ExtractedField, ReportingBasis, ValidationStatus, ValueStatus

SOURCES = {
    "hdfc": {
        "file": "data/raw/hdfc/q2_fy2027_presentation.pdf",
        "basis": ReportingBasis.standalone,
        "rows": [
            ("net_interest_margin", 3.16, "%", 3, "Net interest margin of 3.16% ^ (based on total assets)"),
            ("gnpa", 1.11, "%", 3, "Gross NPA at 1.11%, ex-agri 0.87%"),
            ("nnpa", 0.4, "%", 18, "Net NPA (NNPA) at Sep'26: 0.4% (chart label)"),
            ("casa", 32.0, "%", 15, "CASA ratio, Sep'26 column: 32%"),
            ("capital_adequacy", 18.9, "%", 3, "Capital adequacy ratio at 18.9% of which CET1 at 17.1%"),
            ("average_deposits", 316640.0, "INR crore", 3, "Average deposits at Rs 31,664 bn"),
            ("average_advances", 318720.0, "INR crore", 3, "Average advances under management at Rs 31,872 bn"),
        ],
    },
    "icici": {
        "file": "data/raw/icici/q2_fy2027_presentation.pdf",
        "basis": ReportingBasis.consolidated,
        "rows": [
            ("net_interest_margin", 4.18, "%", 9, "Net interest margin Q2-2027: 4.18%"),
            ("gnpa", 1.20, "%", 17, "Gross NPA ratio at Sep 30, 2026: 1.20%"),
            ("nnpa", 0.30, "%", 17, "Net NPA ratio at Sep 30, 2026: 0.30%"),
            ("provision_coverage", 75.0, "%", 17, "Provision coverage ratio at Sep 30, 2026: 75.0%"),
            ("casa", 35.8, "%", 13, "Average CASA ratio Q2-2027: 35.8%"),
            ("capital_adequacy", 16.62, "%", 57, "Consolidated total capital adequacy at Sep 30, 2026: 16.62%"),
            ("average_deposits", 188821.9, "INR crore", 13, "Average total deposits Q2-2027: Rs 18,882.19 bn"),
        ],
    },
}


def extract() -> dict[str, list[dict]]:
    out = {}
    for slug, cfg in SOURCES.items():
        meta = periods.presentation_meta(slug)
        fields = []
        for name, value, unit, page, note in cfg["rows"]:
            fields.append(ExtractedField(
                company=meta.company or config.COMPANY_BY_SLUG[slug]["name"],
                document_type="investor_presentation",
                financial_year=meta.financial_year, report_period=meta.report_period,
                reporting_basis=cfg["basis"], field_name=name, original_value=note,
                normalized_value=value, currency=("INR" if unit == "INR crore" else None),
                unit=unit, source_value=value, source_unit=unit, scale_factor=1.0,
                source_document=meta.source_document, source_sha256=meta.sha256 or None,
                source_page=page,
                source_table="investor_presentation", source_text=note, confidence=0.95,
                confidence_method="manual_transcription",
                validation_status=ValidationStatus.verified,
                extraction_engine="manual_verified_from_source", model_version="human-review-v1",
                section="bank_key_ratios", value_status=ValueStatus.reported,
                notes="Value transcribed from the cited presentation slide after visual inspection",
                run_id=config.RUN_ID,
            ).model_dump())
        out[slug] = fields
        path = config.STRUCTURED / slug / "bank_ratios.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "slug": slug, "company": meta.company, "basis": cfg["basis"].value,
            "financial_year": meta.financial_year, "report_period": meta.report_period,
            "source_document": meta.source_document, "sha256": meta.sha256,
            "run_id": config.RUN_ID, "fields": fields,
        }, indent=1))
    (config.STRUCTURED / "bank_ratios.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    d = extract()
    for slug, rows in d.items():
        print(slug, len(rows), [(r["field_name"], r["normalized_value"], r["unit"]) for r in rows])
