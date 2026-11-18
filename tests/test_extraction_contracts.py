
import pytest

from src import config
from src.quarterly import extract_quarter
from src.statements import extract_annual


def _path(slug, name):
    p = config.RAW / slug / name
    if not p.exists():
        pytest.skip(f"missing test PDF: {p}")
    return p


def test_hdfc_esop_is_included_in_equity():
    fields = {f.field_name: f for f in extract_annual("hdfc", _path("hdfc", "annual_report_fy2026.pdf"))}
    assert fields["esop"].normalized_value == pytest.approx(4545.11)
    assert fields["equity"].normalized_value == pytest.approx(608444.43)
    assert fields["total_liabilities"].normalized_value == pytest.approx(4908040.84 - 608444.43)
    assert fields["equity"].value_status.value == "derived"


def test_hdfc_bank_pbt_is_not_fabricated():
    fields = {f.field_name: f for f in extract_annual("hdfc", _path("hdfc", "annual_report_fy2026.pdf"))}
    assert "pbt" not in fields
    assert fields["profit_before_minority"].normalized_value == pytest.approx(79219.46)
    assert fields["profit_before_minority"].value_status.value == "derived"


def test_sunpharma_values_are_converted_to_crore():
    fields = {f.field_name: f for f in extract_annual("sunpharma", _path("sunpharma", "annual_report_fy2026.pdf"))}
    rev = fields["revenue"]
    assert rev.normalized_value == pytest.approx(58462.04)
    assert rev.unit == "INR crore"
    assert rev.source_unit == "INR million"
    assert rev.scale_factor == pytest.approx(0.1)
    assert rev.source_value == pytest.approx(584620.4)


def test_airtel_quarterly_is_converted_to_crore():
    fields = {f.field_name: f for f in extract_quarter("airtel", _path("airtel", "q2_fy2027_results.pdf"))}
    assert fields["revenue"].normalized_value == pytest.approx(60877.5)
    assert fields["revenue"].unit == "INR crore"
    assert fields["revenue"].source_unit == "INR million"


def test_tcs_receivables_uses_the_larger_consolidated_row():
    fields = {f.field_name: f for f in extract_annual("tcs", _path("tcs", "annual_report_fy2026.pdf"))}
    assert fields["receivables"].normalized_value == pytest.approx(57630.0)
    assert "57,630" in fields["receivables"].source_text


def test_metadata_is_resolved_from_manifest():
    fields = extract_annual("tcs", _path("tcs", "annual_report_fy2026.pdf"))
    f = fields[0]
    assert f.financial_year == "FY2025-26"
    assert f.report_period == "Year ended 31 March 2026"
    assert f.source_document == "data/raw/tcs/annual_report_fy2026.pdf"
    assert f.source_sha256
    assert f.run_id
