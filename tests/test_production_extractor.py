from src.production_extractor import HybridExtractor, _num


def test_num_formats():
    assert _num("1,075,675") == 1075675
    assert _num("(1,234.50)") == -1234.5
    assert _num("-") == 0
    assert _num("") is None
    assert _num("abc") is None


def test_table_cross_foot():
    ex = HybridExtractor()
    grid = [
        ["Particulars", "2026", "2025"],
        ["A", "10", "8"],
        ["B", "15", "12"],
        ["Total", "25", "20"],
    ]
    checks, status = ex._validate_table(grid)
    assert checks and all(c["passed"] for c in checks)
    assert status in ("verified", "arithmetic_ok")


def test_table_bad_total():
    ex = HybridExtractor()
    grid = [
        ["Particulars", "2026"],
        ["A", "10"],
        ["B", "15"],
        ["Total", "30"],
    ]
    checks, status = ex._validate_table(grid)
    assert checks and not all(c["passed"] for c in checks)
    assert status == "needs_review"


def test_route_detects_scan_and_digital(monkeypatch):
    ex = HybridExtractor()

    class FakePage:
        def __init__(self, text):
            self._text = text
            self.rect = type("R", (), {"width": 100, "height": 100})()

        def get_text(self, *args, **kwargs):
            return self._text

    assert ex._route(FakePage("")) == "blank"
    assert ex._route(FakePage("Short page label only")) == "scanned"
    long_text = ("Revenue from operations and profit for the year are discussed in this section. " * 10)
    assert ex._route(FakePage(long_text)) == "digital"


def test_fuse_table_prefers_numeric_agreement_over_length():
    ex = HybridExtractor()
    table = {
        "grid": [["Revenue", "1,234"]],
        "bboxes": [[[0, 0, 50, 10], [50, 0, 100, 10]]],
    }
    ocr_items = [
        {"text": "1,234", "score": 0.99, "bbox": [55, 1, 95, 9]},
        {"text": "extra", "score": 0.99, "bbox": [0, 1, 40, 9]},
    ]
    grid = ex._fuse_table(table, ocr_items)
    assert grid[0][1] == "1,234"
