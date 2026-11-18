from src.quality import items_to_text, order_items, text_quality_score


def test_text_quality_flags_artefacts():
    good = "Revenue from operations increased during the year. " * 10
    bad = "operntions penxl depredation jlems " * 10
    assert text_quality_score(good) > text_quality_score(bad)
    assert text_quality_score("") == 0.0


def test_order_items_reads_columns_left_to_right():
    # Two columns: left has A/B, right has C/D. A naive y/x sort interleaves
    # A, C, B, D; the XY-cut should return A, B, C, D.
    items = [
        {"text": "A", "bbox": [10, 10, 90, 20]},
        {"text": "B", "bbox": [10, 100, 90, 110]},
        {"text": "C", "bbox": [210, 10, 290, 20]},
        {"text": "D", "bbox": [210, 100, 290, 110]},
    ]
    text = items_to_text(items, 300)
    assert text.index("A") < text.index("B") < text.index("C") < text.index("D")


def test_order_items_single_column():
    items = [
        {"text": "second", "bbox": [10, 100, 90, 110]},
        {"text": "first", "bbox": [10, 10, 90, 20]},
    ]
    ordered = order_items(items, 300)
    assert [x["text"] for x in ordered] == ["first", "second"]
