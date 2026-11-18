"""Extract qualitative disclosures and segment tables with page provenance.

This is deliberately retrieval-first: it records the source passage and page,
not an LLM interpretation. No claim is made that the snippets are complete.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config

CATEGORIES = {
    "management_commentary": [r"management discussion", r"outlook", r"guidance", r"demand environment"],
    "business_developments": [r"acquisition", r"merger", r"demerger", r"commissioned", r"launched",
                              r"strategic partnership", r"joint venture"],
    "risk_disclosures": [r"risk management", r"key risks", r"principal risks", r"risk factors"],
    "auditor_observations": [r"independent auditor", r"auditor'?s? report", r"key audit matter",
                             r"qualified opinion", r"emphasis of matter"],
    "related_party_transactions": [r"related party", r"related-party"],
    "subsidiaries_and_joint_ventures": [r"subsidiar", r"joint venture", r"associate compan"],
}


def snippets_for(path: Path):
    out = {k: [] for k in CATEGORIES}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        text = rec.get("text", "")
        low = text.lower()
        for cat, pats in CATEGORIES.items():
            if len(out[cat]) >= 4:
                continue
            if any(re.search(p, low) for p in pats):
                clean = re.sub(r"\s+", " ", text).strip()
                # choose the sentence window around the first keyword
                m = next((re.search(p, clean, re.I) for p in pats if re.search(p, clean, re.I)), None)
                if m:
                    start = max(0, m.start() - 180)
                    snippet = clean[start:start + 700]
                else:
                    snippet = clean[:700]
                out[cat].append({"page": rec["page"], "section": rec.get("section", ""), "snippet": snippet})
    return out


def extract_all():
    master = {}
    for c in config.COMPANIES:
        slug = c["slug"]
        path = config.PARSED / slug / "annual_report" / "pages.jsonl"
        data = snippets_for(path)
        master[slug] = {"company": c["name"], "sections": data}
        out = config.STRUCTURED / slug / "qualitative_disclosures.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(master[slug], indent=1))
        print(slug, {k: len(v) for k, v in data.items()})
    (config.STRUCTURED / "qualitative_disclosures.json").write_text(json.dumps(master, indent=1))


def segment_tables():
    """Save pages/tables that explicitly mention segment revenue or segment results."""
    master = {}
    for c in config.COMPANIES:
        slug = c["slug"]
        src = config.PARSED / slug / "annual_report" / "pages.jsonl"
        qsrc = config.PARSED / slug / "quarterly_results" / "pages.jsonl"
        found = []
        for path, doc_type in ((src, "annual_report"), (qsrc, "quarterly_results")):
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                rec = json.loads(line)
                t = rec.get("text", "").lower()
                if ("segment revenue" in t or "segment results" in t or "segment information" in t) and rec.get("tables"):
                    found.append({"document_type": doc_type, "page": rec["page"],
                                  "section": rec.get("section", ""), "tables": rec["tables"]})
        master[slug] = found[:10]
        out = config.STRUCTURED / slug / "segment_tables.json"
        out.write_text(json.dumps({"company": c["name"], "segment_tables": master[slug]}, indent=1))
        print(slug, "segment pages", len(master[slug]))
    (config.STRUCTURED / "segment_tables.json").write_text(json.dumps(master, indent=1))


if __name__ == "__main__":
    extract_all()
    segment_tables()
