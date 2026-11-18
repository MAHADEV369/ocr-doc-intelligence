"""Compare extracted fields against the curated ground-truth transcription."""
from __future__ import annotations

import json

from . import config


def run():
    gt = json.loads((config.GROUND_TRUTH / "manual_verification.json").read_text())
    ann = json.loads((config.STRUCTURED / "annual_fields.json").read_text())
    results = []
    for slug, co in gt["companies"].items():
        ext = {r["field_name"]: r for r in ann.get(slug, [])}
        for field, g in co["values"].items():
            e = ext.get(field)
            if not e:
                results.append({"slug": slug, "field": field, "ground_truth": g["value"],
                                "extracted": None, "abs_diff": None, "match": False,
                                "page_match": False, "status": "missing"})
                continue
            diff = abs(abs(e["normalized_value"]) - abs(g["value"]))
            tol = max(1.0, abs(g["value"]) * 0.0005)
            results.append({
                "slug": slug, "field": field, "ground_truth": g["value"],
                "extracted": e["normalized_value"], "abs_diff": round(diff, 4),
                "match": diff <= tol, "page_match": e["source_page"] == g["page"],
                "status": e["validation_status"],
            })
    n = len(results)
    ok = sum(r["match"] for r in results)
    page_ok = sum(r["page_match"] for r in results)
    summary = {"n": n, "exact_or_tolerance_match": ok, "accuracy": round(ok / n, 4),
               "source_page_match": page_ok, "page_accuracy": round(page_ok / n, 4),
               "results": results}
    (config.GROUND_TRUTH / "verification_results.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=1))
    for r in results:
        if not r["match"] or not r["page_match"]:
            print("MISMATCH", r)
    return summary


if __name__ == "__main__":
    run()
