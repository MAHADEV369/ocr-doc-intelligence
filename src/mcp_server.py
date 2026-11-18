"""MCP server exposing the extracted corpus as tools for any LLM chat client.

Run: python -m src.mcp_server
"""
from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP

from . import docstore
from .rag import answer_question

mcp = FastMCP("DocIntel")


@mcp.tool
def list_documents() -> str:
    """List all indexed documents with their ids, company, type and page count."""
    return json.dumps(docstore.list_documents(), indent=1)


@mcp.tool
def search_documents(query: str, doc_id: str | None = None, top_k: int = 6) -> str:
    """Full-text search over page text and tables. Returns snippets with company/page citations."""
    rows = docstore.search(query, doc_id=doc_id, top_k=top_k)
    return json.dumps([{k: r[k] for k in ("doc_id", "company", "doc_type", "period", "page", "snippet")}
                       for r in rows], indent=1)


@mcp.tool
def get_financials(company: str | None = None, doc_id: str | None = None,
                   field_name: str | None = None) -> str:
    """Get exact extracted financial fields (value, unit, period, basis, page, validation status)."""
    rows = docstore.get_fields(doc_id=doc_id, company=company)
    if field_name:
        rows = [r for r in rows if r["field_name"] == field_name]
    return json.dumps(rows, indent=1)


@mcp.tool
def get_page(doc_id: str, page: int) -> str:
    """Get the full extracted text and tables for one page, with provenance."""
    r = docstore.get_page(doc_id, page)
    return json.dumps(r, indent=1) if r else f"Page {page} not found in {doc_id}"


@mcp.tool
def ask_documents(question: str, doc_id: str | None = None) -> str:
    """Ask a grounded question. Uses structured facts first, then retrieved pages and the local LLM.
    Returns an answer plus page citations and the exact facts used."""
    r = answer_question(question, doc_id=doc_id)
    lines = [r["answer"], "", f"[mode: {r['mode']}]"]
    if r["sources"]:
        lines.append("Sources:")
        seen = set()
        for s in r["sources"]:
            k = (s["company"], s["page"])
            if k in seen:
                continue
            seen.add(k)
            lines.append(f"- {s['company']} p.{s['page']} ({s['doc_type']})")
    return "\n".join(lines)


@mcp.tool
def extract_pdf(path: str, max_pages: int = 5, company: str | None = None) -> str:
    """Run the hybrid extractor on a local PDF (digital + scanned routing) and add it to the index."""
    r = docstore.ingest_hybrid(Path(path), name=Path(path).name, max_pages=max_pages, company=company)
    return json.dumps(r, indent=1)


if __name__ == "__main__":
    mcp.run()
