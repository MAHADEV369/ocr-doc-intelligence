"""Run one OCR/document engine across the benchmark pages.

Usage: python -m benchmark.run_engine --engine tesseract
Results are appended to data/benchmark/results_<engine>.jsonl
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
import traceback
from pathlib import Path

from src import config
from src.engines import get_engine

BENCH = config.BENCHMARK


def _rss(v: float) -> float:
    # macOS reports ru_maxrss in bytes, Linux in KB
    return v / (1024 * 1024) if sys.platform == "darwin" else v / 1024


def rss_mb() -> tuple[float, float, float]:
    """Return (max, parent, children) peak RSS in MB.

    MinerU and OCRmyPDF run as subprocesses. Measuring only RUSAGE_SELF
    reported the parent client's memory, not the OCR worker's.
    """
    parent = _rss(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    children = _rss(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return round(max(parent, children), 1), round(parent, 1), round(children, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--repeats", type=int, default=1)
    args = ap.parse_args()
    pages = json.loads((BENCH / args.manifest).read_text())
    if args.limit:
        pages = pages[: args.limit]
    out_path = BENCH / f"results_{args.engine}{args.suffix}.jsonl"
    engine = get_engine(args.engine)
    t0 = time.perf_counter()
    try:
        engine._ensure()
    except Exception as e:
        (BENCH / f"run_{args.engine}.error").write_text(str(e))
        print("LOAD FAILED", e)
        return
    load_s = time.perf_counter() - t0
    rss_now, _, _ = rss_mb()
    print(f"{args.engine} loaded in {load_s:.2f}s; rss={rss_now:.0f}MB")
    with open(out_path, "w") as f:
        for i, p in enumerate(pages, 1):
            for rep in range(1, args.repeats + 1):
                res = None
                for attempt in (1, 2):
                    try:
                        res = engine.run(Path(p["single_page_pdf"]), Path(p["image"]))
                        break
                    except Exception:
                        err = traceback.format_exc()[-1500:]
                        if attempt == 2:
                            res = type("R", (), {"text": "", "markdown": "", "tables": [],
                                                 "elapsed_s": 0, "error": err,
                                                 "model_version": engine.version})()
                peak, parent, children = rss_mb()
                empty = not (res.text or "").strip()
                err = res.error or ("empty output" if empty else "")
                rec = {"key": p.get("key") or f"{p['slug']}_{p['kind']}",
                       "slug": p["slug"], "kind": p["kind"], "page": p["page"],
                       "repeat": rep, "engine": args.engine,
                       "text": res.text, "markdown": res.markdown,
                       "tables": res.tables, "html_tables": getattr(res, "html_tables", []),
                       "elapsed_s": round(res.elapsed_s, 3), "load_s": round(load_s, 3),
                       "rss_mb": peak, "rss_parent_mb": parent, "rss_children_mb": children,
                       "error": err, "empty": empty,
                       "confidence": getattr(res, "confidence", None),
                       "model_version": res.model_version}
                f.write(json.dumps(rec) + "\n")
                print(f"[{i}/{len(pages)} r{rep}] {p['slug']:11s} {p['kind']:14s} "
                      f"p{p['page']:<4d} {res.elapsed_s:6.2f}s rss={peak:.0f}MB "
                      f"err={bool(err)}", flush=True)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
