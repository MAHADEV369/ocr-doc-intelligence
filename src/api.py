"""FastAPI service exposing the extracted dataset, provenance and benchmark results."""
from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config, review

app = FastAPI(
    title="Indian Corporate Document Intelligence API",
    version="1.1.0",
    description="Self-hosted extraction of Indian corporate annual reports, quarterly results and investor presentations. "
                "Every field carries page-level provenance.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class ReviewDecision(BaseModel):
    status: str
    reviewer: str
    note: str = ""


MASTER = config.DATA / "master_dataset.csv"
UPLOADS = config.STRUCTURED / "uploads"
_df = None
_bench = None


def require_token(x_api_token: str | None = Header(default=None)):
    if not config.API_TOKEN:
        return True
    if x_api_token != config.API_TOKEN:
        raise HTTPException(401, "invalid or missing X-API-Token")
    return True


def df() -> pd.DataFrame:
    global _df
    if _df is None:
        _df = pd.read_csv(MASTER)
    return _df


def benchmark() -> pd.DataFrame:
    global _bench
    if _bench is None:
        p = config.BENCHMARK / "engine_summary.csv"
        _bench = pd.read_csv(p) if p.exists() else pd.DataFrame()
    return _bench


def records(frame: pd.DataFrame) -> list[dict]:
    """Convert NaN to None so FastAPI emits valid JSON, without stringifying numbers."""
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")


@app.post("/extract", dependencies=[Depends(require_token)])
async def extract_pdf(file: UploadFile = File(...), max_pages: int = Query(3, le=50),
                      force_ocr: bool = False, dpi: int = Query(300, ge=150, le=400)):
    """Run the hybrid extractor on an uploaded PDF and return page-level JSON.

    The heavy CPU work runs in a worker thread so one upload cannot block the
    event loop. Results are persisted under data/structured/uploads/<job_id>/.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF uploads are supported")
    tmpdir = Path(tempfile.mkdtemp(prefix="docintel_"))
    src = tmpdir / "input.pdf"
    size = 0
    try:
        with open(src, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"PDF exceeds {config.MAX_UPLOAD_MB} MB")
                out.write(chunk)
        with open(src, "rb") as fh:
            if fh.read(5) != b"%PDF-":
                raise HTTPException(400, "file is not a PDF")
        from .production_extractor import HybridExtractor
        job_id = uuid.uuid4().hex
        out_dir = UPLOADS / job_id
        ex = HybridExtractor(dpi=dpi, force_ocr=force_ocr)
        result = await run_in_threadpool(ex.extract, src, out_dir, max_pages)
        result["job_id"] = job_id
        result["output_dir"] = str(out_dir)
        (out_dir / "result.json").write_text(json.dumps(result, indent=1))
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/jobs/{job_id}", dependencies=[Depends(require_token)])
def job(job_id: str):
    if not job_id.isalnum():
        raise HTTPException(400, "invalid job id")
    p = UPLOADS / job_id / "result.json"
    if not p.exists():
        raise HTTPException(404, "job not found")
    return json.loads(p.read_text())


@app.get("/review/queue", dependencies=[Depends(require_token)])
def review_queue(limit: int = Query(100, le=5000)):
    q = review.queue_df()
    return {"count": int(len(q)), "records": records(q.head(limit))}


@app.post("/review/{review_id}", dependencies=[Depends(require_token)])
def review_decision(review_id: str, body: ReviewDecision):
    if not review_id.isalnum():
        raise HTTPException(400, "invalid review id")
    try:
        decision = review.apply_decision(review_id, body.status, body.reviewer, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    review.sync_master()
    global _df
    _df = None
    return {"review_id": review_id, "decision": decision}


@app.get("/health")
def health():
    d = df()
    return {"status": "ok", "records": int(len(d)), "companies": int(d["company"].nunique())}


@app.get("/companies")
def companies():
    d = df()
    g = d.groupby("company").agg(records=("field_name", "count"),
                                 documents=("source_document", "nunique")).reset_index()
    return records(g)


@app.get("/companies/{slug}")
def company(slug: str):
    if slug not in config.COMPANY_BY_SLUG:
        raise HTTPException(404, "unknown company")
    name = config.COMPANY_BY_SLUG[slug]["name"]
    d = df()[df()["company"] == name]
    return {"company": name, "slug": slug, "records": records(d)}


@app.get("/fields")
def fields(company: Optional[str] = None, field_name: Optional[str] = None,
           financial_year: Optional[str] = None, limit: int = Query(500, le=5000)):
    d = df()
    if company:
        d = d[d["company"].str.contains(company, case=False, na=False)]
    if field_name:
        d = d[d["field_name"] == field_name]
    if financial_year:
        d = d[d["financial_year"] == financial_year]
    return records(d.head(limit))


@app.get("/documents")
def documents():
    out = []
    for f in sorted(config.MANIFESTS.glob("*.json")):
        out.extend(json.loads(f.read_text()).get("documents", []))
    return out


@app.get("/benchmark")
def bench():
    return records(benchmark())


@app.get("/stats")
def stats():
    d = df()
    return {
        "records": int(len(d)),
        "companies": int(d["company"].nunique()),
        "documents": int(d["source_document"].nunique()),
        "verified": int((d["validation_status"] == "verified").sum()),
        "arithmetic_ok": int((d["validation_status"] == "arithmetic_ok").sum()),
        "needs_review": int((d["validation_status"] == "needs_review").sum()),
        "reported": int((d["value_status"] == "reported").sum()),
        "derived": int((d["value_status"] == "derived").sum()),
        "year_split": d.groupby("financial_year").size().to_dict(),
        "engine_split": d.groupby("extraction_engine").size().to_dict(),
    }
