from src.units import UnitInfo, detect_unit, is_unit_header, normalise_unit_text


def test_crore_default():
    info = detect_unit("(Amount in ₹ crore)")
    assert info.multiplier == 1.0
    assert info.source_unit == "INR crore"
    assert info.canonical_unit == "INR crore"


def test_million_and_plural():
    assert detect_unit("₹ in Million").multiplier == 0.1
    assert detect_unit("(All amounts are in millions of Indian Rupee)").multiplier == 0.1
    assert detect_unit("USD in millions").source_unit == "INR million"


def test_thousand_and_lakh_are_not_corrupted_by_h_replacement():
    assert detect_unit("(Amount in ₹ thousand)").multiplier == 0.0001
    assert detect_unit("(₹ in thousand)").source_unit == "INR thousand"
    assert detect_unit("(₹ in lakh)").multiplier == 0.01
    assert detect_unit("(₹ in lakhs)").source_unit == "INR lakh"


def test_000s_marker():
    info = detect_unit("` in ‘000s")
    assert info.multiplier == 0.0001
    assert info.source_unit == "INR thousand"


def test_units_are_not_detected_in_random_words():
    # The old implementation replaced every "h", which corrupted "thousand"
    # and "lakh"; this is a regression guard.
    assert "thousand" in normalise_unit_text("amount in thousand")
    assert detect_unit("the company has lakhs of customers").multiplier == 0.01
    assert is_unit_header("(Amount in ₹ crore)")
    assert not is_unit_header("Profit for the year")


def test_to_canonical():
    info = UnitInfo(multiplier=0.1, source_unit="INR million")
    assert info.to_canonical(584620.4) == 58462.04
