"""Local LLM chat app with grounded document extraction and citations."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, docstore
from .rag import answer_question

app = FastAPI(title="DocIntel Chat", version="1.0.0")
STATIC = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str
    doc_id: Optional[str] = None
    history: list[dict] = []


@app.on_event("startup")
def startup():
    docstore.init()
    try:
        n = docstore._count("pages")
    except Exception:
        n = 0
    if n == 0:
        docstore.ingest_corpus()


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "chat.html").read_text()


@app.get("/api/health")
def health():
    return {"status": "ok", "documents": docstore._count("documents"),
            "pages": docstore._count("pages"), "fields": docstore._count("fields")}


@app.get("/api/documents")
def documents():
    return docstore.list_documents()


@app.get("/api/fields")
def fields(doc_id: Optional[str] = None, company: Optional[str] = None):
    return docstore.get_fields(doc_id=doc_id, company=company)


@app.get("/api/document/{doc_id}/page/{page}")
def page(doc_id: str, page: int):
    r = docstore.get_page(doc_id, page)
    if not r:
        raise HTTPException(404, "page not found")
    return r


@app.post("/api/upload")
def upload(file: UploadFile = File(...), max_pages: int = Form(5), company: str = Form("")):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF files are supported")
    tmpdir = Path(tempfile.mkdtemp(prefix="docintel_chat_"))
    src = tmpdir / "upload.pdf"
    size = 0
    with open(src, "wb") as f:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                shutil.rmtree(tmpdir, ignore_errors=True)
                raise HTTPException(413, f"PDF exceeds {config.MAX_UPLOAD_MB} MB")
            f.write(chunk)
    try:
        res = docstore.ingest_hybrid(src, name=file.filename, max_pages=max_pages,
                                     company=company or None)
        return res
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "empty message")
    return answer_question(req.message, doc_id=req.doc_id or None, history=req.history)
