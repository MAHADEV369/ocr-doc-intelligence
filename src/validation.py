"""Pandera validation for the master dataset.

Pydantic validates individual records; Pandera validates the table-level
contract (types, allowed statuses, unit arithmetic, page numbers).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera import Check, Column, DataFrameSchema

from . import config

VALUE_STATUSES = ["reported", "derived", "nil", "not_reported", "not_extractable"]
VALIDATION_STATUSES = ["verified", "arithmetic_ok", "needs_review", "failed", "not_applicable"]


def _unit_ok(series: pd.Series) -> pd.Series:
    s = series.astype("string")
    return s.isna() | s.eq("%") | s.str.startswith("INR ")


def _unit_math_ok(df: pd.DataFrame) -> pd.Series:
    has = df["source_value"].notna() & df["scale_factor"].notna() & df["normalized_value"].notna()
    expected = df["source_value"] * df["scale_factor"]
    ok = (expected - df["normalized_value"]).abs() <= np.maximum(0.01, expected.abs() * 1e-6)
    return ~has | ok


SCHEMA = DataFrameSchema(
    {
        "company": Column(str, nullable=False),
        "document_type": Column(str, checks=Check.isin(
            ["annual_report", "quarterly_results", "investor_presentation"])),
        "financial_year": Column(str, nullable=False),
        "report_period": Column(str, nullable=False),
        "reporting_basis": Column(str, checks=Check.isin(["consolidated", "standalone", "unknown"])),
        "field_name": Column(str, nullable=False),
        "original_value": Column(str, nullable=False),
        "normalized_value": Column(float, nullable=True,
                                   checks=Check(lambda s: s.isna() | np.isfinite(s))),
        "currency": Column(str, nullable=True),
        "unit": Column(str, nullable=False, checks=Check(_unit_ok)),
        "source_value": Column(float, nullable=True,
                               checks=Check(lambda s: s.isna() | np.isfinite(s))),
        "source_unit": Column(str, nullable=True),
        "scale_factor": Column(float, nullable=True,
                               checks=Check(lambda s: s.isna() | ((s > 0) & np.isfinite(s)))),
        "value_status": Column(str, checks=Check.isin(VALUE_STATUSES)),
        "is_derived": Column(bool, nullable=False),
        "formula": Column(str, nullable=True),
        "source_document": Column(str, nullable=False),
        "source_page": Column("Int64", nullable=True, checks=Check(lambda s: s.isna() | (s >= 1))),
        "source_page_label": Column(str, nullable=True),
        "source_table": Column(str, nullable=True),
        "source_text": Column(str, nullable=False),
        "source_sha256": Column(str, nullable=True),
        "confidence": Column(float, nullable=True, checks=Check.in_range(0, 1)),
        "validation_status": Column(str, checks=Check.isin(VALIDATION_STATUSES)),
        "extraction_engine": Column(str, nullable=False),
        "model_version": Column(str, nullable=False),
        "run_id": Column(str, nullable=True),
    },
    strict=False,
    coerce=True,
    checks=[
        Check(_unit_math_ok, error="normalized_value != source_value * scale_factor"),
    ],
)

def _derived_ok(df: pd.DataFrame) -> pd.Series:
    return (df["value_status"] != "derived") | (df["formula"].fillna("").str.len() > 0)


def validate_master(df: pd.DataFrame, strict: bool = False) -> dict:
    report = {"rows": int(len(df)), "passed": True, "errors": []}
    try:
        SCHEMA.validate(df, lazy=True)
        bad = df[~_derived_ok(df)]
        if len(bad):
            report["passed"] = False
            report["errors"] = [{"error": "derived rows must include a formula",
                                 "rows": bad.index.tolist()[:20]}]
            if strict:
                raise ValueError("derived rows must include a formula")
            return report
    except pa.errors.SchemaErrors as exc:
        report["passed"] = False
        report["errors"] = json.loads(exc.failure_cases.to_json(orient="records"))
    except Exception as exc:  # pragma: no cover - defensive
        report["passed"] = False
        report["errors"] = [{"error": str(exc)}]
    if strict and not report["passed"]:
        raise ValueError(f"master dataset failed validation: {report['errors'][:5]}")
    return report


def write_report(df: pd.DataFrame) -> dict:
    report = validate_master(df)
    (config.DATA / "pandera_report.json").write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    p = Path(config.DATA / "master_dataset.csv")
    report = write_report(pd.read_csv(p))
    print(json.dumps({k: v for k, v in report.items() if k != "errors"}, indent=1))
    if report["errors"]:
        print(json.dumps(report["errors"][:10], indent=1))
