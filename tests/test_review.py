import pandas as pd

from src import review


def test_record_id_is_stable():
    row = {"company": "A", "document_type": "annual_report", "financial_year": "FY2025-26",
           "field_name": "revenue", "source_document": "x.pdf", "source_page": 10}
    assert review.record_id(row) == review.record_id(row)
    assert review.record_id(row) != review.record_id({**row, "source_page": 11})


def test_queue_contains_only_review_fields():
    df = pd.DataFrame([
        {"company": "A", "document_type": "annual_report", "financial_year": "FY2025-26",
         "field_name": "revenue", "source_document": "x.pdf", "source_page": 10,
         "validation_status": "needs_review", "value_status": "reported", "confidence": 0.9},
        {"company": "A", "document_type": "annual_report", "financial_year": "FY2025-26",
         "field_name": "pat", "source_document": "x.pdf", "source_page": 10,
         "validation_status": "verified", "value_status": "reported", "confidence": 0.9},
    ])
    q = review.queue_df(df)
    assert len(q) == 1
    assert q.iloc[0]["field_name"] == "revenue"
    assert len(q.iloc[0]["review_id"]) == 12
