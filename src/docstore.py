"""SQLite document store + full-text search for the LLM chat tool.

The store indexes the already-extracted 30-document corpus, and can ingest new
PDFs through the production hybrid extractor.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config

DB_PATH = config.DATA / "chat.db"

FIELD_SYNONYMS = {
    "revenue": ["revenue", "sales", "turnover", "total income", "top line"],
    "pat": ["pat", "profit after tax", "net profit", "profit for the year", "bottom line"],
    "pbt": ["pbt", "profit before tax"],
    "ebitda": ["ebitda", "operating profit"],
    "eps_basic": ["eps", "earnings per share", "basic eps"],
    "total_assets": ["total assets", "assets"],
    "total_liabilities": ["total liabilities", "liabilities"],
    "equity": ["equity", "net worth", "shareholders funds", "shareholders' funds"],
    "borrowings": ["borrowings", "debt", "loans"],
    "cash": ["cash", "cash and equivalents"],
    "investments": ["investments"],
    "cfo": ["cfo", "operating cash flow", "cash from operations"],
    "cfi": ["cfi", "investing cash flow"],
    "cff": ["cff", "financing cash flow"],
    "capex": ["capex", "capital expenditure"],
    "free_cash_flow": ["free cash flow", "fcf"],
    "deposits": ["deposits"],
    "advances": ["advances", "loans and advances"],
    "net_interest_income": ["nii", "net interest income"],
    "net_interest_margin": ["nim", "net interest margin"],
    "gnpa": ["gnpa", "gross npa", "gross non performing"],
    "nnpa": ["nnpa", "net npa", "net non performing"],
    "provision_coverage": ["pcr", "provision coverage"],
    "capital_adequacy": ["car", "capital adequacy", "crar"],
    "casa": ["casa", "casa ratio"],
}

COMPANY_NAMES = {c["slug"]: c["name"] for c in config.COMPANIES}
STOPWORDS = set("""a an and are as at be by for from has have how in is it its of on or that the
this to was were what when where which who why with year years fy company report""".split())


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init():
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY, company TEXT, name TEXT, doc_type TEXT, period TEXT,
        path TEXT, pages INTEGER, basis TEXT, created TEXT
    );
    CREATE TABLE IF NOT EXISTS pages (
        doc_id TEXT, page INTEGER, text TEXT, tables_json TEXT, route TEXT, engine TEXT,
        PRIMARY KEY (doc_id, page)
    );
    CREATE TABLE IF NOT EXISTS fields (
        id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, company TEXT, field_name TEXT,
        value REAL, unit TEXT, currency TEXT, page INTEGER, status TEXT, source_text TEXT,
        period TEXT, basis TEXT, engine TEXT
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
        doc_id UNINDEXED, page UNINDEXED, text, tokenize='porter'
    );
    """)
    con.commit(); con.close()


def _doc_id(slug, doc_type):
    return f"{slug}_{doc_type}"


def ingest_corpus(reset: bool = False):
    init()
    con = connect()
    if reset:
        con.executescript("DELETE FROM documents; DELETE FROM pages; DELETE FROM fields; DELETE FROM pages_fts;")
        con.commit()
    docs = []
    for mpath in sorted(config.MANIFESTS.glob("*.json")):
        m = json.loads(mpath.read_text())
        slug = m["slug"]
        for d in m["documents"]:
            doc_id = _doc_id(slug, d["doc_type"])
            con.execute("""INSERT OR REPLACE INTO documents
                (id,company,name,doc_type,period,path,pages,basis,created)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                        (doc_id, m["company"], d.get("title", ""), d["doc_type"], d.get("period", ""),
                         d["file"], d.get("pages", 0), "consolidated", datetime.now(timezone.utc).isoformat()))
            pj = config.PARSED / slug / d["doc_type"] / "pages.jsonl"
            if not pj.exists():
                continue
            for line in pj.read_text().splitlines():
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                text = rec.get("text", "")
                tables = rec.get("tables") or []
                table_text = "\n".join(" | ".join(str(c) for c in row) for t in tables for row in t)
                full = (text + "\n" + table_text).strip()
                con.execute("""INSERT OR REPLACE INTO pages
                    (doc_id,page,text,tables_json,route,engine) VALUES (?,?,?,?,?,?)""",
                            (doc_id, rec["page"], full, json.dumps(tables),
                             rec.get("route", "digital"),
                             "tesseract" if rec.get("ocr") else "native_pymupdf"))
                con.execute("INSERT INTO pages_fts (doc_id,page,text) VALUES (?,?,?)",
                            (doc_id, rec["page"], full))
            docs.append(doc_id)
    master = pd.read_csv(config.DATA / "master_dataset.csv").fillna("")
    for _, r in master.iterrows():
        doc_id = None
        slug = _slug_from_company(r["company"])
        # Prefer the source path: company display names can change (e.g. Tata
        # Motors' former-name suffix) while the directory slug is stable.
        parts = Path(str(r["source_document"])).parts
        if "raw" in parts:
            idx = parts.index("raw")
            if idx + 1 < len(parts):
                slug = parts[idx + 1]
        candidate = f"{slug}_{r['document_type']}"
        if candidate in docs:
            doc_id = candidate
        else:
            for d in docs:
                if d.startswith(f"{slug}_"):
                    doc_id = d
                    break
        if not doc_id:
            continue
        con.execute("""INSERT INTO fields
            (doc_id,company,field_name,value,unit,currency,page,status,source_text,period,basis,engine)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (doc_id, r["company"], r["field_name"], r["normalized_value"], r["unit"],
                     r["currency"], r["source_page"], r["validation_status"], r["source_text"],
                     r["report_period"], r["reporting_basis"], r["extraction_engine"]))
    con.commit(); con.close()
    return {"documents": len(docs), "pages": _count("pages"), "fields": _count("fields")}


def _slug_from_company(name: str) -> str:
    for c in config.COMPANIES:
        if c["name"] == name:
            return c["slug"]
    return name.lower().split()[0]


def _count(table: str) -> int:
    con = connect()
    n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    con.close()
    return n


def list_documents(company: str | None = None):
    con = connect()
    q = "SELECT * FROM documents"
    args = []
    if company:
        q += " WHERE company LIKE ?"
        args.append(f"%{company}%")
    q += " ORDER BY company, doc_type"
    rows = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return rows


def search(query: str, doc_id: str | None = None, top_k: int = 6, company: str | None = None):
    con = connect()
    tokens = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9%.,'-]+", query)
              if t.lower() not in STOPWORDS]
    if not tokens:
        tokens = [query]
    fts_q = " OR ".join('"' + t.replace('"', '') + '"' for t in tokens[:12])
    args = [fts_q]
    where = ""
    if doc_id:
        where += " AND doc_id = ?"
        args.append(doc_id)
    if company:
        where += " AND doc_id IN (SELECT id FROM documents WHERE company = ?)"
        args.append(company)
    try:
        rows = con.execute(f"""
            SELECT doc_id, page, snippet(pages_fts,2,'[',']','…',30) AS snip,
                   bm25(pages_fts) AS score
            FROM pages_fts WHERE pages_fts MATCH ? {where}
            ORDER BY rank LIMIT ?""", args + [top_k]).fetchall()
    except Exception:
        rows = []
    if not rows:
        like = f"%{query.split()[0]}%"
        sql = "SELECT doc_id,page,substr(text,1,900) AS snip,0 AS score FROM pages WHERE text LIKE ?"
        a = [like]
        if doc_id:
            sql += " AND doc_id=?"
            a.append(doc_id)
        if company:
            sql += " AND doc_id IN (SELECT id FROM documents WHERE company=?)"
            a.append(company)
        rows = con.execute(sql + " LIMIT ?", a + [top_k]).fetchall()
    out = []
    for r in rows:
        meta = con.execute("SELECT company,doc_type,period FROM documents WHERE id=?", (r["doc_id"],)).fetchone()
        full = con.execute("SELECT text FROM pages WHERE doc_id=? AND page=?", (r["doc_id"], r["page"])).fetchone()
        out.append({"doc_id": r["doc_id"], "company": meta["company"] if meta else r["doc_id"],
                    "doc_type": meta["doc_type"] if meta else "", "period": meta["period"] if meta else "",
                    "page": r["page"], "snippet": r["snip"], "score": round(float(r["score"] or 0), 4),
                    "text": full["text"] if full else ""})
    con.close()
    return out


def detect_companies(question: str):
    q = question.lower()
    found = []
    for c in config.COMPANIES:
        if c["name"].lower() in q or re.search(rf"\b{re.escape(c['slug'])}\b", q):
            found.append(c["name"])
    aliases = {"reliance": "Reliance Industries Limited", "hdfc": "HDFC Bank Limited",
               "tcs": "Tata Consultancy Services Limited", "icici": "ICICI Bank Limited",
               "infosys": "Infosys Limited", "l&t": "Larsen & Toubro Limited",
               "larsen": "Larsen & Toubro Limited", "itc": "ITC Limited",
               "tata motors": "Tata Motors Limited", "sun pharma": "Sun Pharmaceutical Industries Limited",
               "airtel": "Bharti Airtel Limited"}
    for k, v in aliases.items():
        if re.search(rf"\b{re.escape(k)}\b", q) and v not in found:
            found.append(v)
    return found


def detect_company(question: str):
    found = detect_companies(question)
    return found[0] if found else None


def find_fields(question: str, doc_id: str | None = None, company: str | None = None):
    q = question.lower()
    wanted = []
    for field, syns in FIELD_SYNONYMS.items():
        if any(re.search(rf"\b{re.escape(s)}\b", q) for s in syns):
            wanted.append(field)
    if not wanted:
        return []
    con = connect()
    placeholders = ",".join("?" for _ in wanted)
    sql = f"SELECT * FROM fields WHERE field_name IN ({placeholders})"
    args = list(wanted)
    if doc_id:
        sql += " AND doc_id=?"; args.append(doc_id)
    if company:
        sql += " AND company=?"; args.append(company)
    sql += " ORDER BY period DESC, field_name"
    try:
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    except Exception:
        rows = []
    con.close()
    return rows


def get_page(doc_id: str, page: int):
    con = connect()
    r = con.execute("SELECT * FROM pages WHERE doc_id=? AND page=?", (doc_id, page)).fetchone()
    d = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    con.close()
    if not r:
        return None
    return {"document": dict(d) if d else None, "page": r["page"], "text": r["text"],
            "tables": json.loads(r["tables_json"] or "[]")}


def get_fields(doc_id: str | None = None, company: str | None = None):
    con = connect()
    sql = "SELECT * FROM fields WHERE 1=1"; args = []
    if doc_id:
        sql += " AND doc_id=?"; args.append(doc_id)
    if company:
        sql += " AND company=?"; args.append(company)
    sql += " ORDER BY company, period DESC, field_name"
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    return rows


def ingest_hybrid(path: Path, name: str | None = None, max_pages: int | None = None,
                  company: str | None = None):
    from .production_extractor import HybridExtractor
    ex = HybridExtractor(dpi=300)
    result = ex.extract(path, config.DATA / "chat_uploads" / Path(path).stem, max_pages=max_pages)
    doc_id = "upload_" + uuid.uuid4().hex[:8]
    con = connect()
    con.execute("""INSERT OR REPLACE INTO documents
        (id,company,name,doc_type,period,path,pages,basis,created) VALUES (?,?,?,?,?,?,?,?,?)""",
                (doc_id, company or "Uploaded document", name or Path(path).name, "uploaded_pdf", "",
                 str(path), result["profile"]["pages"], "", datetime.now(timezone.utc).isoformat()))
    for p in result["pages"]:
        table_text = "\n".join(" | ".join(str(c) for c in row) for t in p["tables"] for row in t["grid"])
        full = (p["text"] + "\n" + table_text).strip()
        con.execute("""INSERT INTO pages (doc_id,page,text,tables_json,route,engine) VALUES (?,?,?,?,?,?)""",
                    (doc_id, p["page"], full, json.dumps([t["grid"] for t in p["tables"]]),
                     p["route"], p["engine"]))
        con.execute("INSERT INTO pages_fts (doc_id,page,text) VALUES (?,?,?)", (doc_id, p["page"], full))
    con.commit(); con.close()
    return {"doc_id": doc_id, "pages": result["profile"]["pages"], "summary": result["summary"]}


if __name__ == "__main__":
    # Rebuild rather than append: the master dataset is the source of truth.
    print(ingest_corpus(reset=True))
