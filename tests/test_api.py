import pytest
from fastapi.testclient import TestClient

from src import config
from src.api import app

pytestmark = pytest.mark.skipif(
    not (config.DATA / "master_dataset.csv").exists(),
    reason="generated master dataset is not included in the code/reports repository",
)


def test_health_and_stats():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["records"] > 0
    s = client.get("/stats")
    assert s.status_code == 200
    assert "reported" in s.json()


def test_fields_returns_numbers_not_strings():
    client = TestClient(app)
    r = client.get("/fields", params={"company": "Reliance", "field_name": "pat"})
    assert r.status_code == 200
    rows = r.json()
    assert rows and isinstance(rows[0]["normalized_value"], (int, float))


def test_rejects_non_pdf_upload():
    client = TestClient(app)
    r = client.post("/extract", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_review_queue_endpoint():
    client = TestClient(app)
    r = client.get("/review/queue", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    assert len(body["records"]) <= 5
