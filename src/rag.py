"""Retrieval + grounded answering for the LLM chat tool.

The LLM never supplies numbers on its own: facts come from the structured field
table, context comes from page text, and every number in the answer is checked
against the supplied context. If the check fails, the deterministic extractive
answer is returned instead.
"""
from __future__ import annotations

import os
import re

import requests

from . import docstore

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("DOCINTEL_LLM_MODEL", "qwen3.5:9b")
MAX_CONTEXT_CHARS = 2200

SYSTEM = """You are DocIntel, a financial-document analyst working only from extracted evidence.

Rules:
1. The FACTS block is authoritative. CONTEXT is supporting evidence. If they conflict, use FACTS.
2. Answer only from FACTS/CONTEXT. Do not use outside knowledge.
3. Every number must be copied exactly from FACTS. Never calculate, round, or invent a number unless the user explicitly asks for a calculation; if calculating, show the formula and inputs.
4. Cite every factual claim in the exact form [Reliance p.101], [HDFC Bank p.3], [TCS p.167]. Never write "Company", "PAGE", or a placeholder.
5. FY2025-26 means the year ended 31 March 2026. A fact labelled "Year ended 31 Mar 2026" IS FY2025-26; do not claim it is absent.
6. Distinguish consolidated from standalone. If basis is unknown, say so.
7. If the evidence is insufficient, say "The extracted documents do not contain enough evidence to answer that."
8. Be concise. Prefer a short table or bullets for financial values.
9. Never describe a missing value as zero."""


def _fmt_num(v):
    if v is None:
        return "null"
    if isinstance(v, float) and v.is_integer():
        return f"{v:,.0f}"
    return f"{v:,}"


FIELD_LABELS = {
    "revenue": "Revenue", "pat": "PAT", "pbt": "PBT", "ebitda": "EBITDA",
    "eps_basic": "Basic EPS", "total_assets": "Total assets", "total_liabilities": "Total liabilities",
    "equity": "Equity", "borrowings": "Borrowings", "cash": "Cash and equivalents",
    "investments": "Investments", "cfo": "Operating cash flow", "cfi": "Investing cash flow",
    "cff": "Financing cash flow", "capex": "Capex", "free_cash_flow": "Free cash flow",
    "deposits": "Deposits", "advances": "Advances", "net_interest_income": "Net interest income",
    "net_interest_margin": "NIM", "gnpa": "Gross NPA", "nnpa": "Net NPA",
    "provision_coverage": "Provision coverage", "capital_adequacy": "Capital adequacy",
    "casa": "CASA ratio", "other_income": "Other income", "operating_expenses": "Operating expenses",
    "provisions": "Provisions",
}


def _period_intent(question: str):
    q = question.lower()
    if re.search(r"q2|q-2|quarter|three months|h1|half year", q):
        return "quarter"
    if re.search(r"fy\s*25|fy\s*2025|fy26|fy\s*2026|annual|full year|year ended", q):
        return "annual"
    return None


def _fy(period: str):
    p = (period or "").lower()
    if "year ended" in p:
        return "FY2025-26"
    if "q2" in p:
        return "Q2 FY2026-27"
    return period


def build_context(question: str, doc_id: str | None = None, top_k: int = 6):
    companies = docstore.detect_companies(question)
    company = companies[0] if len(companies) == 1 else None
    pages = docstore.search(question, doc_id=doc_id, top_k=top_k, company=company)
    fields = docstore.find_fields(question, doc_id=doc_id, company=company)
    if len(companies) > 1:
        fields = [f for f in fields if f["company"] in companies]
    intent = _period_intent(question)
    if intent == "annual":
        filtered = [f for f in fields if "year ended" in (f["period"] or "").lower()]
        if filtered:
            fields = filtered
    elif intent == "quarter":
        filtered = [f for f in fields if "q2" in (f["period"] or "").lower()]
        if filtered:
            fields = filtered
    seen = set(); unique = []
    for f in fields:
        k = (f["company"], f["field_name"], _fy(f["period"]))
        if k in seen:
            continue
        seen.add(k); unique.append(f)
    def rank(f):
        order = {"revenue": 0, "pat": 1, "pbt": 2, "ebitda": 3, "eps_basic": 4}
        return (order.get(f["field_name"], 10), f["company"])
    unique.sort(key=rank)
    facts = "\n".join(
        f"- {f['company']} | {FIELD_LABELS.get(f['field_name'], f['field_name'])} = "
        f"{_fmt_num(f['value'])} {f['unit'] or ''} | {_fy(f['period'])} | {f['basis']} | "
        f"source [p.{f['page']}] | status={f['status']}"
        for f in unique[:24])
    blocks = []
    for p in pages:
        text = re.sub(r"\s+", " ", p["text"] or "")[:MAX_CONTEXT_CHARS]
        blocks.append(f"--- {p['company']} | {p['doc_type']} | {p['period']} | page {p['page']} ---\n{text}")
    context = "\n\n".join(blocks) if blocks else "(no matching pages)"
    return {"company": company, "companies": companies, "pages": pages, "fields": unique,
            "facts": facts, "context": context, "period_intent": intent}


def _numbers(text: str):
    out = set()
    for tok in re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", text):
        t = tok.strip("()").replace(",", "")
        try:
            v = float(t)
        except ValueError:
            continue
        out.add(round(abs(v), 4))
    return out


def llm_call(messages: list[dict], model: str = LLM_MODEL, timeout: int = 180):
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model, "messages": messages, "stream": False, "think": False,
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 700},
    }, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def deterministic_answer(ctx) -> str:
    if ctx["fields"]:
        lines = ["**Extracted values**", ""]
        for f in ctx["fields"][:12]:
            short = f["company"].replace(" Limited", "").replace(" Industries", "")
            lines.append(f"- {f['company']} — {FIELD_LABELS.get(f['field_name'], f['field_name'])}: "
                         f"**{_fmt_num(f['value'])} {f['unit'] or ''}** "
                         f"({_fy(f['period'])}, {f['basis']}) [{short} p.{f['page']}]")
        lines += ["", "Source: structured extraction from the cited pages; see the citations below."]
        return "\n".join(lines)
    if ctx["pages"]:
        lines = ["**Relevant extracted passages**", ""]
        for p in ctx["pages"][:4]:
            snip = re.sub(r"\s+", " ", p["snippet"] or "")[:500]
            lines.append(f"- {p['company']} ({p['doc_type']}, p.{p['page']}): {snip}")
        return "\n".join(lines)
    return "The extracted documents do not contain enough evidence to answer that."


def answer_question(question: str, doc_id: str | None = None, history: list[dict] | None = None):
    ctx = build_context(question, doc_id=doc_id)
    sources = []
    seen_src = set()
    for p in ctx["pages"]:
        k = (p["company"], p["page"])
        if k in seen_src:
            continue
        seen_src.add(k)
        sources.append({"company": p["company"], "doc_id": p["doc_id"], "doc_type": p["doc_type"],
                        "period": p["period"], "page": p["page"], "snippet": (p["snippet"] or "")[:400]})
    facts = [{"company": f["company"], "field": f["field_name"], "value": f["value"],
              "unit": f["unit"], "page": f["page"], "period": f["period"],
              "basis": f["basis"], "status": f["status"]} for f in ctx["fields"]]
    messages = [{"role": "system", "content": SYSTEM}]
    for h in (history or [])[-4:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"][:1500]})
    user = f"""QUESTION
{question}

FACTS (structured, already extracted)
{ctx['facts'] or '(none)'}

CONTEXT (page text)
{ctx['context']}
"""
    messages.append({"role": "user", "content": user})
    mode = "llm"
    model = LLM_MODEL
    # Numeric questions are answered deterministically from structured facts.
    numeric_intent = bool(ctx["fields"]) and bool(re.search(
        r"\b(what|how much|value|reported|revenue|sales|pat|pbt|profit|ebitda|eps|assets|equity|"
        r"borrowings|debt|cash|cfo|capex|fcf|deposits|advances|npa|casa|nim|car|ratio)\b",
        question.lower())) and not re.search(
        r"\b(summar|commentary|outlook|risk|why|explain|trend|strategy|guidance|develop)\b",
        question.lower())
    if numeric_intent:
        fsources = []; seen_f = set()
        for f in ctx["fields"][:20]:
            k = (f["company"], f["page"])
            if k in seen_f:
                continue
            seen_f.add(k)
            fsources.append({"company": f["company"], "doc_id": f.get("doc_id", ""),
                             "doc_type": "structured_field", "period": f"{_fy(f['period'])} ({f['basis']})",
                             "page": f["page"], "snippet": f["source_text"]})
        return {"answer": deterministic_answer(ctx), "mode": "structured_facts", "model": "none",
                "sources": fsources, "facts": facts}
    try:
        answer = llm_call(messages)
    except Exception as e:
        answer = deterministic_answer(ctx)
        mode = f"extractive_fallback ({type(e).__name__})"
        model = "none"
    # Normalise the model's citation style if it literalised the template.
    answer = re.sub(r"\[Company p\.PAGE (\d+)\]", r"[p.\1]", answer)
    # Guard: every 3+ digit number in the LLM answer must exist in the supplied evidence.
    if mode == "llm":
        allowed = _numbers(ctx["context"] + "\n" + ctx["facts"])
        # Citations such as [Reliance p.101] are page metadata, not financial
        # claims. Remove them before checking numeric grounding so small values
        # (EPS, NIM, NPA ratios) are checked too, not just numbers >= 1000.
        answer_body = re.sub(r"\[[^\]]*\]", " ", answer)
        used = _numbers(answer_body)
        unverified = sorted(n for n in used if n not in allowed)
        if unverified:
            answer = deterministic_answer(ctx)
            mode = "extractive_fallback (unverified numbers: " + ", ".join(f"{n:g}" for n in unverified[:5]) + ")"
            model = "none"
    return {"answer": answer, "mode": mode, "model": model,
            "sources": sources, "facts": facts}
