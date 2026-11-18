from benchmark.metrics import norm_text, numbers, numeric_prf, table_scores


def test_markdown_is_stripped_for_cer():
    a = norm_text("# Revenue\n\n**1,234** | 567")
    b = norm_text("Revenue\n1,234 567")
    assert a == b


def test_numeric_sign_is_preserved():
    pre, rec, f1 = numeric_prf([-100.0, 200.0], [-100.0, 200.0])
    assert (pre, rec, f1) == (1.0, 1.0, 1.0)
    pre, rec, _ = numeric_prf([-100.0], [100.0])
    assert pre == 0.0 and rec == 0.0


def test_header_year_is_ignored():
    text = "As at March 31, 2026\nRevenue 1,234"
    assert 2026 not in numbers(text)
    assert 1234 in numbers(text)


def test_table_scores_penalise_extra_tables():
    gold = [[["A", "1"], ["Total", "1"]]]
    good = [[["A", "1"], ["Total", "1"]]]
    extra = good + [[["X", "9"], ["Y", "8"]]]
    p_good, r_good, _, tp_good, tr_good = table_scores(gold, good)
    p_extra, r_extra, _, _, _ = table_scores(gold, extra)
    assert r_good == 1.0 and tr_good == 1.0
    assert p_extra <= p_good
    assert r_extra <= r_good
