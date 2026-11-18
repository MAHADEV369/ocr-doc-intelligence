"""Render the extended 100-page benchmark summary."""
from __future__ import annotations

import pandas as pd

from src import config

B = config.BENCHMARK


def build():
    s = pd.read_csv(B / "engine_summary_extended.csv")
    p = pd.read_csv(B / "page_metrics_extended.csv")
    stmt = p[(p["kind"] == "financial_table") & p["table_cell_recall"].notna()]
    tab = stmt.groupby("engine").agg(
        cell=("table_cell_recall", "mean"),
        text=("table_text_recall", "mean"),
        struct=("table_structure", "mean"),
    ).reset_index() if len(stmt) else pd.DataFrame()
    L = ["# Extended benchmark (100 pages)", "",
         f"Pages: **{p[['slug', 'kind', 'page']].drop_duplicates().shape[0]}** · "
         f"Runs per engine: **{int(s['n_runs'].max())}** · "
         f"Engine-page runs: **{len(p)}**", "",
         "| Engine | Group | Numeric F1 | 95% CI | CER | 95% CI | Table cell recall (statement) | Table structure | Median s/page | Peak RSS MB | Runs |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, r in s.sort_values("rank_score", ascending=False).iterrows():
        row = tab[tab["engine"] == r["engine"]]
        cell = f"{row.iloc[0]['cell']:.3f}" if len(row) else "n/a"
        struct = f"{row.iloc[0]['struct']:.3f}" if len(row) else "n/a"
        L.append(f"| {r['engine']} | {r.get('rank_group', '—')} | {r['num_f1']:.3f} | "
                 f"±{r.get('num_f1_ci95', float('nan')):.3f} | {r['cer']:.3f} | "
                 f"±{r.get('cer_ci95', float('nan')):.3f} | {cell} | {struct} | "
                 f"{r['median_s']:.2f} | {r['peak_rss_mb']:.0f} | {int(r['n_runs'])} |")
    L += ["", "The extended set is stratified across the ten annual reports: statement pages, "
          "dense notes/table pages and narrative pages. Gold text remains the publisher's native "
          "text layer, not an independent human transcription. CIs are 95% page-level intervals "
          "(1.96 × standard error across pages)."]
    failed = p[p["error"]]
    if len(failed):
        L += ["", "Failures: " + "; ".join(
            f"{r.engine} {r.slug} {r.kind} p{r.page}" for r in failed.itertuples())]
    L += ["", "PaddleOCR and MinerU were not run on the extended set: at ~44 s/page and ~37 s/page "
          "respectively, a 100-page pass would take 1–1.5 hours per engine on this host. Their "
          "20-page benchmark results remain in `engine_summary.csv`."]
    missing = set(s["engine"]) - set(p["engine"])
    if missing:
        L += ["", f"Engines not run on the extended set: {', '.join(sorted(missing))}."]
    (config.REPORTS / "benchmark_extended.md").write_text("\n".join(L) + "\n")
    print("wrote", config.REPORTS / "benchmark_extended.md")


if __name__ == "__main__":
    build()
