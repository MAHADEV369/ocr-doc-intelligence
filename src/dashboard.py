"""Build the results dashboard and executive report from generated artefacts."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from . import config


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def build():
    manifests = [json.loads(p.read_text()) for p in sorted(config.MANIFESTS.glob("*.json"))]
    docs = [d for m in manifests for d in m["documents"]]
    pages = sum(d.get("pages", 0) for d in docs)
    parse_meta = load_json(config.STRUCTURED / "parse_meta.json", [])
    annual = load_json(config.STRUCTURED / "annual_fields.json", {})
    quarterly = load_json(config.STRUCTURED / "quarterly_fields.json", {})
    bank = load_json(config.STRUCTURED / "bank_ratios.json", {})
    gt = load_json(config.GROUND_TRUTH / "verification_results.json", {})
    exp = load_json(config.STRUCTURED / "export_summary.json", [])
    bench = pd.read_csv(config.BENCHMARK / "engine_summary.csv") if (config.BENCHMARK / "engine_summary.csv").exists() else pd.DataFrame()
    page_metrics = pd.read_csv(config.BENCHMARK / "page_metrics.csv") if (config.BENCHMARK / "page_metrics.csv").exists() else pd.DataFrame()

    n_fields = sum(len(v) for v in annual.values()) + sum(len(v) for v in quarterly.values()) + sum(len(v) for v in bank.values())
    ocr_pages = sum(len(m.get("ocr_pages", [])) for m in parse_meta)
    total_parse_s = sum(m.get("processing_seconds", 0) for m in parse_meta)
    validation_records = sum(e.get("provenance_total", e.get("validation_total", 0)) for e in exp)
    validation_passed = sum(e.get("provenance_passed", e.get("validation_passed", 0)) for e in exp)
    accuracy_records = sum(e.get("accuracy_total", 0) for e in exp)
    accuracy_passed = sum(e.get("accuracy_passed", 0) for e in exp)
    pandera = load_json(config.DATA / "pandera_report.json", {})

    dash = {
        "generated": str(date.today()),
        "companies_processed": len({m["slug"] for m in manifests}),
        "documents_collected": len(docs),
        "documents_by_type": pd.Series([d["doc_type"] for d in docs]).value_counts().to_dict(),
        "total_pages": pages,
        "pages_native_parsed": sum(m.get("pages", 0) for m in parse_meta),
        "pages_ocr_fallback": ocr_pages,
        "fields_extracted": n_fields,
        "documents_successfully_parsed": len(parse_meta),
        "document_success_rate_pct": round(100 * len(parse_meta) / max(1, len(docs)), 1),
        "total_parse_seconds": round(total_parse_s, 1),
        "pages_per_second_native": round(sum(m.get("pages", 0) for m in parse_meta) / max(1, total_parse_s), 3),
        "ground_truth_fields": gt.get("n"),
        "ground_truth_accuracy": gt.get("accuracy"),
        "source_page_accuracy": gt.get("page_accuracy"),
        "validation_provenance_passed": validation_passed,
        "validation_provenance_total": validation_records,
        "validation_accuracy_passed": accuracy_passed,
        "validation_accuracy_total": accuracy_records,
        "pandera_master_schema_passed": bool(pandera.get("passed")),
        "records_requiring_manual_review": int(
            sum(1 for v in annual.values() for f in v if f["validation_status"] == "needs_review") +
            sum(1 for v in quarterly.values() for f in v if f["validation_status"] == "needs_review") +
            sum(1 for v in bank.values() for f in v if f["validation_status"] == "needs_review")
        ),
        "failed_documents": len(docs) - len(parse_meta),
        "engines_tested": sorted(bench["engine"].tolist()) if len(bench) else [],
    }
    if len(bench):
        best = bench.sort_values("rank_score", ascending=False).iloc[0]
        dash["best_engine"] = best["engine"]
        dash["best_engine_numeric_f1"] = round(float(best["num_f1"]), 4)
        dash["best_engine_table_recall"] = round(float(best["table_cell_recall"]), 4)
        if len(page_metrics) and "table_cell_recall" in page_metrics:
            stmt = page_metrics[(page_metrics["kind"] == "financial_table")
                                & page_metrics["table_cell_recall"].notna()]
            if len(stmt):
                g = stmt.groupby("engine")["table_cell_recall"].mean().sort_values(ascending=False)
                dash["best_statement_table_recall"] = round(float(g.iloc[0]), 4)
                dash["best_statement_table_engine"] = g.index[0]
        dash["fastest_median_s"] = round(float(bench["median_s"].min()), 2)
        dash["lowest_peak_rss_mb"] = round(float(bench["peak_rss_mb"].min()), 0)
        if "rank_group" in bench:
            tc = bench[bench["rank_group"] == "table-capable"]
            to = bench[bench["rank_group"] == "text-only"]
            if len(tc):
                dash["best_table_capable_engine"] = tc.sort_values("rank_score", ascending=False).iloc[0]["engine"]
            if len(to):
                dash["best_text_only_engine"] = to.sort_values("rank_score", ascending=False).iloc[0]["engine"]

    (config.REPORTS / "dashboard.json").write_text(json.dumps(dash, indent=1))

    lines = ["# Results dashboard — Indian corporate document intelligence", "",
             f"Generated: {date.today()}", "",
             "| Metric | Value |", "|---|---|"]
    labels = {
        "companies_processed": "Companies processed",
        "documents_collected": "Documents collected",
        "total_pages": "Total pages collected",
        "pages_native_parsed": "Pages parsed (all)",
        "pages_ocr_fallback": "Pages OCR'd (scanned/image-only fallback)",
        "fields_extracted": "Structured fields extracted",
        "document_success_rate_pct": "Document success rate (%)",
        "total_parse_seconds": "Total native parse time (s)",
        "pages_per_second_native": "Native parse throughput (pages/s)",
        "ground_truth_accuracy": "Curated source-transcription accuracy",
        "source_page_accuracy": "Source-page traceability",
        "validation_provenance_passed": "Provenance checks passed",
        "validation_provenance_total": "Provenance checks total",
        "validation_accuracy_passed": "Independent arithmetic checks passed",
        "validation_accuracy_total": "Independent arithmetic checks total",
        "pandera_master_schema_passed": "Pandera master-schema validation passed",
        "records_requiring_manual_review": "Records flagged for manual review",
        "best_statement_table_recall": "Best statement-page table-cell recall",
        "best_statement_table_engine": "Best statement-page table engine",
        "failed_documents": "Failed documents",
    }
    for k, lab in labels.items():
        v = dash.get(k)
        if isinstance(v, float):
            v = round(v, 4)
        lines.append(f"| {lab} | {v} |")
    if len(bench):
        lines += ["", "## Engine ranking", "",
                  "| Rank | Engine | Group | Numeric F1 | Key-number recall | Table cell recall | CER | Median s/page | Peak RSS (MB) |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for i, (_, r) in enumerate(bench.sort_values("rank_score", ascending=False).iterrows(), 1):
            lines.append(f"| {i} | {r['engine']} | {r.get('rank_group', '—')} | {r['num_f1']:.3f} | "
                         f"{r['key_number_recall']:.3f} | {r['table_cell_recall']:.3f} | "
                         f"{r['cer']:.3f} | {r['median_s']:.2f} | {r['peak_rss_mb']:.0f} |")
    (config.REPORTS / "dashboard.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dash, indent=1))
    return dash


if __name__ == "__main__":
    build()
