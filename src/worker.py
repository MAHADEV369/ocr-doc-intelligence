"""Celery worker entrypoint for asynchronous document processing."""
from __future__ import annotations

import os
from pathlib import Path

from celery import Celery

from .parse import process_document
from .production_extractor import HybridExtractor
from .quarterly import extract_quarter
from .statements import extract_annual

REDIS = os.getenv("REDIS_URL", "redis://localhost:6379/0")
app = Celery("docintel", broker=REDIS, backend=REDIS)
app.conf.update(
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=int(os.getenv("WORKER_MAX_TASKS_PER_CHILD", "20")),
    task_time_limit=int(os.getenv("TASK_TIME_LIMIT", "3600")),
    task_soft_time_limit=int(os.getenv("TASK_SOFT_TIME_LIMIT", "3300")),
    result_expires=86400,
)
app.conf.task_routes = {
    "docintel.hybrid_extract_task": {"queue": "documents"},
    "docintel.process_document_task": {"queue": "documents"},
}


def _retry(self, exc):
    # Retry only transient failures; malformed/missing inputs should fail fast.
    if isinstance(exc, (FileNotFoundError, ValueError, PermissionError)):
        raise exc
    raise self.retry(exc=exc, countdown=min(300, 10 * (2 ** self.request.retries)))


@app.task(bind=True, max_retries=3, name="docintel.hybrid_extract_task")
def hybrid_extract_task(self, file_path: str, max_pages: int | None = None, force_ocr: bool = False):
    try:
        ex = HybridExtractor(dpi=300, force_ocr=force_ocr)
        return ex.extract(Path(file_path), max_pages=max_pages)
    except Exception as exc:
        _retry(self, exc)


@app.task(bind=True, max_retries=3, name="docintel.process_document_task")
def process_document_task(self, slug: str, doc_type: str, file_path: str):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    try:
        meta = process_document(slug, doc_type, path)
        fields = []
        if doc_type == "annual_report":
            fields = [f.model_dump(mode="json") for f in extract_annual(slug, path)]
        elif doc_type == "quarterly_results":
            fields = [f.model_dump(mode="json") for f in extract_quarter(slug, path)]
        return {"meta": meta, "fields": fields}
    except Exception as exc:
        _retry(self, exc)
