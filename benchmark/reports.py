"""Split the benchmark summary into the required comparison artefacts."""
from __future__ import annotations

import json

import pandas as pd

from src import config

B = config.BENCHMARK


def build():
    s = pd.read_csv(B / "engine_summary.csv")
    p = pd.read_csv(B / "page_metrics.csv")
    cols = [c for c in ["engine", "cer", "wer", "num_recall", "num_f1", "key_number_recall", "line_order",
                        "rank_group", "rank_score"] if c in s]
    s[cols].to_csv(B / "ocr_comparison.csv", index=False)
    table_cols = [c for c in ["engine", "table_cell_recall", "table_text_recall", "table_structure"]
                  if c in s]
    s[table_cols].to_csv(B / "table_comparison.csv", index=False)
    s[["engine", "pages", "median_s", "p95_s"]] \
        .to_csv(B / "speed_comparison.csv", index=False)
    s[["engine", "peak_rss_mb", "failures"]] \
        .to_csv(B / "resource_comparison.csv", index=False)
    # company x engine scorecard
    p.pivot_table(index="slug", columns="engine", values="num_f1", aggfunc="mean") \
        .to_csv(B / "company_engine_scorecard.csv")
    # failure rows
    fails = []
    for f in B.glob("results_*.jsonl"):
        if "_degraded" in f.name:
            continue
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("error"):
                fails.append({"engine": r["engine"], "slug": r["slug"], "kind": r["kind"],
                              "page": r["page"], "error": r["error"][:1000]})
    pd.DataFrame(fails).to_csv(B / "failures.csv", index=False)
    L = ["# Failure analysis", "",
         f"Total engine-page failures recorded: **{len(fails)}** of {len(p)} engine-page runs.", ""]
    for e in s["engine"]:
        n = len([x for x in fails if x["engine"] == e])
        L.append(f"- {e}: {n} failures")
    L += ["", "## Failure detail", "",
          "| Engine | Company | Page | Error |", "|---|---|---:|---|"]
    for x in fails:
        L.append(f"| {x['engine']} | {x['slug']} | {x['page']} | {x['error'].splitlines()[-1][:180]} |")
    L += ["", "## Non-run engines", "",
          "- **olmOCR 0.4.27**: blocked, requires CUDA/vLLM; no macOS backend. Model weights are Apache-2.0.",
          "- **Unstructured**: not a standalone OCR engine; hi_res delegates OCR and its model stack was not installed.",
          "", "## Measurement notes", "",
          "- Empty output is counted as a failure, not a successful run.",
          "- Memory is measured for the engine process and any child process (MinerU/OCRmyPDF run in subprocesses).",
          "- Runtime warnings are captured in the per-run logs; they are not silently discarded."]
    (config.REPORTS / "failure_analysis.md").write_text("\n".join(L) + "\n")
    print("wrote comparison CSVs and failure analysis")
    print(s.to_string(index=False))


if __name__ == "__main__":
    build()
