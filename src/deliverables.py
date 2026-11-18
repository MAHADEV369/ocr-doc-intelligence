"""Assemble the deliverable bundle and a machine-readable file index."""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import date

from . import config

OUT = config.DELIVERABLES


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    copies = {
        config.DATA / "master_dataset.csv": "master_dataset.csv",
        config.DATA / "master_dataset.parquet": "master_dataset.parquet",
        config.DATA / "master_dataset.xlsx": "master_dataset.xlsx",
        config.DATA / "master_company_summary.csv": "master_company_summary.csv",
        config.DATA / "coverage_matrix.csv": "coverage_matrix.csv",
        config.DATA / "review_queue.csv": "review_queue.csv",
        config.DATA / "pandera_report.json": "pandera_report.json",
        config.ROOT / "README.md": "README.md",
        config.ROOT / ".env.example": ".env.example",
        config.ROOT / "requirements.txt": "requirements.txt",
        config.ROOT / "Dockerfile": "Dockerfile",
        config.ROOT / "docker-compose.yml": "docker-compose.yml",
        config.ROOT / "db" / "schema.sql": "schema.sql",
        config.DATA / "master_company_summary.xlsx": "master_company_summary.xlsx",
        config.BENCHMARK / "engine_summary.csv": "benchmark_engine_summary.csv",
        config.BENCHMARK / "engine_summary_extended.csv": "benchmark_engine_summary_extended.csv",
        config.BENCHMARK / "page_metrics_extended.csv": "benchmark_page_metrics_extended.csv",
        config.BENCHMARK / "page_metrics.csv": "benchmark_page_metrics.csv",
        config.BENCHMARK / "degraded_metrics.csv": "benchmark_degraded_metrics.csv",
        config.BENCHMARK / "ocr_comparison.csv": "benchmark_ocr_comparison.csv",
        config.BENCHMARK / "table_comparison.csv": "benchmark_table_comparison.csv",
        config.BENCHMARK / "speed_comparison.csv": "benchmark_speed_comparison.csv",
        config.BENCHMARK / "resource_comparison.csv": "benchmark_resource_comparison.csv",
        config.BENCHMARK / "company_engine_scorecard.csv": "benchmark_company_scorecard.csv",
        config.BENCHMARK / "failures.csv": "benchmark_failures.csv",
        config.REPORTS / "failure_analysis.md": "failure_analysis.md",
        config.REPORTS / "data_quality.md": "data_quality.md",
        config.REPORTS / "document_inventory.md": "document_inventory.md",
        config.REPORTS / "ocr_engine_research.md": "ocr_engine_research.md",
        config.REPORTS / "production_extractor.md": "production_extractor.md",
        config.REPORTS / "llm_chat_tool.md": "llm_chat_tool.md",
        config.ROOT / "tools" / "openai_tools.json": "openai_tools.json",
        config.REPORTS / "executive_report.md": "executive_report.md",
        config.REPORTS / "dashboard.md": "dashboard.md",
        config.REPORTS / "dashboard.json": "dashboard.json",
        config.REPORTS / "company_financials.md": "company_financials.md",
        config.REPORTS / "engine_research.json": "engine_research.json",
        config.REPORTS / "benchmark_methodology.md": "benchmark_methodology.md",
        config.REPORTS / "benchmark_extended.md": "benchmark_extended.md",
        config.REPORTS / "production_architecture.md": "production_architecture.md",
        config.REPORTS / "hardware.md": "hardware.md",
        config.GROUND_TRUTH / "verification_results.json": "ground_truth_verification.json",
        config.GROUND_TRUTH / "manual_verification.json": "ground_truth_manual.json",
    }
    index = []
    for src, name in copies.items():
        if src.exists():
            shutil.copy2(src, OUT / name)
            index.append({"name": name, "path": str((OUT / name).relative_to(config.ROOT)),
                          "bytes": (OUT / name).stat().st_size})
    # company packages index
    for c in config.COMPANIES:
        d = config.COMPANY_DATASETS / c["slug"]
        if d.exists():
            index.append({"name": f"{c['name']} package", "path": str(d.relative_to(config.ROOT)),
                          "bytes": sum(p.stat().st_size for p in d.rglob("*") if p.is_file())})
    index.append({"name": "Original source PDFs", "path": "data/raw/",
                  "bytes": sum(p.stat().st_size for p in (config.RAW).rglob("*.pdf"))})
    index.append({"name": "Parsed page JSONL + Markdown + tables", "path": "data/parsed/",
                  "bytes": sum(p.stat().st_size for p in (config.PARSED).rglob("*") if p.is_file())})
    index.append({"name": "Raw engine outputs", "path": "data/benchmark/results_*.jsonl",
                  "bytes": sum(p.stat().st_size for p in config.BENCHMARK.glob("results_*.jsonl"))})
    (OUT / "file_index.json").write_text(json.dumps({"generated": str(date.today()), "files": index}, indent=1))

    # bundle reports + company datasets + benchmark CSV/JSONL (exclude 228 MB originals)
    zpath = OUT / "docintel_reports_and_datasets.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in config.REPORTS.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(config.ROOT))
        for p in config.COMPANY_DATASETS.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(config.ROOT))
        for p in [config.DATA / "master_dataset.csv", config.DATA / "master_dataset.parquet",
                  config.DATA / "master_dataset.xlsx", config.DATA / "master_company_summary.csv",
                  config.DATA / "master_company_summary.xlsx", config.DATA / "coverage_matrix.csv",
                  config.DATA / "review_queue.csv", config.DATA / "pandera_report.json"]:
            if p.exists():
                z.write(p, p.relative_to(config.ROOT))
        for p in config.BENCHMARK.glob("*.csv"):
            z.write(p, p.relative_to(config.ROOT))
        for p in config.BENCHMARK.glob("results_*.jsonl"):
            z.write(p, p.relative_to(config.ROOT))
        z.write(OUT / "file_index.json", "deliverables/file_index.json")
    print("bundle", zpath, zpath.stat().st_size)
    print("files", len(index))


if __name__ == "__main__":
    build()
