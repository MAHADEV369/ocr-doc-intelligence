from src.periods import _period_end, parse_financial_year


def test_financial_year_variants():
    assert parse_financial_year("FY2025-26 (year ended 31 March 2026)") == "FY2025-26"
    assert parse_financial_year("Q2 FY2026-27 (quarter ended 30 September 2026)") == "FY2026-27"
    assert parse_financial_year("2025-2026") == "FY2025-26"
    assert parse_financial_year("no year here") == ""


def test_report_period():
    assert _period_end("Year ended 31 March 2026") == "Year ended 31 March 2026"
    assert _period_end("Quarter ended 30 September 2026") == "Quarter ended 30 September 2026"
    assert _period_end("year ended 31 Mar 2026") == ""
