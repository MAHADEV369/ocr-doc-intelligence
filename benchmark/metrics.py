"""Benchmark metrics: CER/WER, numeric recall, reading order, tables, speed."""
from __future__ import annotations

import json
import re

import jiwer
import numpy as np
import pandas as pd

from src import config
from src.text_utils import clean_text
from src.units import detect_unit

BENCH = config.BENCHMARK
NUM_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
HEADER_WORDS = re.compile(
    r"\b(year ended|financial year|as at|as of|march|june|september|december|fy\s?\d|"
    r"annual report|integrated report|page|particulars|schedule|note no)\b", re.I)


def norm_text(s: str) -> str:
    """Markdown-neutral text for CER/WER.

    Docling and MinerU return Markdown; Tesseract returns plain text. Without
    stripping Markdown, heading hashes and bold markers look like OCR errors.
    """
    s = clean_text(s, markdown=True)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip().lower()


def norm_line(s: str) -> str:
    return clean_text(s, markdown=True).strip().lower()


def numbers(s: str) -> list[float]:
    """Signed numeric tokens; header-only year rows are ignored."""
    out = []
    for line in (s or "").splitlines():
        toks = NUM_RE.findall(line)
        if HEADER_WORDS.search(line) and len(toks) <= 3 and not re.search(
                r"₹|\binr\b|crore|million|lakh|thousand", line, re.I):
            continue
        for tok in toks:
            neg = tok.startswith("(") and tok.endswith(")")
            t = tok.strip("()").replace(",", "")
            try:
                v = float(t)
            except ValueError:
                continue
            out.append(-v if neg else v)
    return out


def cell_text(value) -> str:
    return re.sub(r"\s+", " ", clean_text(str(value), markdown=True)).strip().lower()


def numeric_prf(gold: list[float], hyp: list[float]) -> tuple[float, float, float]:
    """Signed multiset precision/recall/F1."""
    from collections import Counter
    g = Counter(round(x, 2) for x in gold)
    h = Counter(round(x, 2) for x in hyp)
    tp = sum(min(g[k], h[k]) for k in g)
    prec = tp / max(1, sum(h.values()))
    rec = tp / max(1, sum(g.values()))
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    return prec, rec, f1


def text_prf(gold: list[str], hyp: list[str]) -> tuple[float, float]:
    from collections import Counter
    g = Counter(cell_text(x) for x in gold if cell_text(x))
    h = Counter(cell_text(x) for x in hyp if cell_text(x))
    tp = sum(min(g[k], h[k]) for k in g)
    return tp / max(1, sum(h.values())), tp / max(1, sum(g.values()))


def line_order(gold: str, hyp: str) -> float:
    import difflib
    g = [norm_line(x) for x in gold.splitlines() if norm_line(x)]
    h = [norm_line(x) for x in hyp.splitlines() if norm_line(x)]
    if not g or not h:
        return 0.0
    return difflib.SequenceMatcher(a=g, b=h, autojunk=False).ratio()


def table_scores(gold_tables: list, eng_tables: list) -> tuple[float, float, float, float, float]:
    """Return numeric P/R, structure similarity and text-cell P/R.

    Each gold table is matched to one engine table by combined numeric and
    text agreement. Unmatched engine tables are counted in the precision
    denominator, so emitting many spurious tables is penalised.
    """
    if not gold_tables or not eng_tables:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    from collections import Counter
    total_num_tp = total_num_g = total_num_e = 0
    total_txt_tp = total_txt_g = total_txt_e = 0
    struct = []
    used: set[int] = set()
    for gt in gold_tables:
        gnums = [x for row in gt for c in row for x in numbers(c)]
        gtext = [c for row in gt for c in row if cell_text(c)]
        if not gnums and not gtext:
            continue
        best = None
        for ei, et in enumerate(eng_tables):
            if ei in used:
                continue
            enums = [x for row in et for c in row for x in numbers(c)]
            etext = [c for row in et for c in row if cell_text(c)]
            n_prec, n_rec, n_f1 = numeric_prf(gnums, enums)
            t_prec, t_rec = text_prf(gtext, etext)
            score = 0.6 * n_f1 + 0.4 * (2 * t_prec * t_rec / max(1e-9, t_prec + t_rec))
            if best is None or score > best[0]:
                best = (score, ei, et, gnums, enums, gtext, etext)
        if best:
            _score, ei, et, gnums, enums, gtext, etext = best
            used.add(ei)
            for k, n in Counter(round(x, 2) for x in gnums).items():
                total_num_tp += min(n, Counter(round(x, 2) for x in enums)[k])
            total_num_g += len(gnums)
            total_num_e += len(enums)
            gc = Counter(cell_text(x) for x in gtext if cell_text(x))
            ec = Counter(cell_text(x) for x in etext if cell_text(x))
            total_txt_tp += sum(min(gc[k], ec[k]) for k in gc)
            total_txt_g += len(gtext)
            total_txt_e += len(etext)
            gr, gcc = len(gt), max(len(r) for r in gt)
            er, ecc = len(et), max((len(r) for r in et), default=0)
            gcells = sum(len(r) for r in gt)
            ecells = sum(len(r) for r in et)
            struct.append(max(0.0, 1 - (
                abs(gr - er) + abs(gcc - ecc) + abs(gcells - ecells)
            ) / max(1, gr + gcc + gcells + er + ecc + ecells)))
    # Count unused engine tables as false positives.
    for ei, et in enumerate(eng_tables):
        if ei in used:
            continue
        total_num_e += sum(1 for row in et for c in row for _ in numbers(c))
        total_txt_e += sum(1 for row in et for c in row if cell_text(c))
    return (
        total_num_tp / max(1, total_num_e),
        total_num_tp / max(1, total_num_g),
        (sum(struct) / len(struct) if struct else 0.0),
        total_txt_tp / max(1, total_txt_e),
        total_txt_tp / max(1, total_txt_g),
    )


def degraded_metrics() -> pd.DataFrame:
    """Rebuild the degraded-scan metrics from results_*_degraded.jsonl."""
    rows = []
    for f in sorted(BENCH.glob("results_*_degraded.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = f"{r['slug']}_{r['kind']}"
            gold = (BENCH / "pages" / key / "gold.txt").read_text()
            hyp = r.get("text") or ""
            if not hyp.strip():
                cer = wer = 1.0
                pre = rec = f1 = 0.0
                lo = 0.0
            else:
                pre, rec, f1 = numeric_prf(numbers(gold), numbers(hyp))
                try:
                    cer = jiwer.cer(norm_text(gold), norm_text(hyp))
                    wer = jiwer.wer(norm_text(gold), norm_text(hyp))
                except Exception:
                    cer = wer = 1.0
                lo = line_order(gold, hyp)
            rows.append({"engine": r["engine"], "set": "degraded", "slug": r["slug"],
                         "cer": cer, "wer": wer, "num_f1": f1, "num_recall": rec,
                         "line_order": lo, "seconds": r["elapsed_s"],
                         "error": bool(r.get("error")) or not hyp.strip()})
    df = pd.DataFrame(rows)
    if len(df):
        df.to_csv(BENCH / "degraded_metrics.csv", index=False)
    return df


def main(manifest_name: str = "manifest.json", suffix: str = ""):
    focus = json.loads((BENCH / "focus_values.json").read_text())
    if suffix:
        files = sorted(BENCH.glob(f"results_*{suffix}.jsonl"))
        page_root = BENCH / "pages_extended"
    else:
        files = [f for f in sorted(BENCH.glob("results_*.jsonl"))
                 if "_degraded" not in f.name and "_extended" not in f.name]
        page_root = BENCH / "pages"
    rows = []
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = r.get("key") or f"{r['slug']}_{r['kind']}"
            base = page_root / key
            gold = (base / "gold.txt").read_text()
            gtables = json.loads((base / "gold_tables.json").read_text())
            hyp = r["text"] or ""
            empty = not hyp.strip()
            if empty:
                pre = rec = f1 = 0.0
                cer = wer = 1.0
                lo = 0.0
            else:
                gn, hn = numbers(gold), numbers(hyp)
                pre, rec, f1 = numeric_prf(gn, hn)
                try:
                    cer = jiwer.cer(norm_text(gold), norm_text(hyp))
                    wer = jiwer.wer(norm_text(gold), norm_text(hyp))
                except Exception:
                    cer = wer = 1.0
                lo = line_order(gold, hyp)
            if gtables:
                tpre, trec, tstruct, ttext_prec, ttext_rec = table_scores(
                    gtables, r.get("tables") or [])
            else:
                tpre = trec = tstruct = ttext_prec = ttext_rec = float("nan")
            # key financial values present on table page
            kv = focus.get(r["slug"], {})
            hn = numbers(hyp)
            hits = 0; total = 0
            if r["kind"] == "financial_table":
                kv = {k: v for k, v in kv.items() if k in ("revenue", "pbt", "pat", "total_income")}
                if not kv:
                    kv = focus.get(r["slug"], {})
                # Focus values are stored in crore; convert the target into
                # the unit printed on the page.
                unit_mult = 1.0 / max(1e-12, detect_unit(gold).multiplier)
                for name, val in kv.items():
                    total += 1
                    target = abs(val) * unit_mult
                    if any(abs(abs(x) - target) <= max(1.0, target * 0.0005) for x in hn):
                        hits += 1
            rows.append({
                "engine": r["engine"], "key": key, "repeat": r.get("repeat", 1),
                "slug": r["slug"], "kind": r["kind"], "page": r["page"],
                "cer": cer, "wer": wer, "num_precision": pre, "num_recall": rec, "num_f1": f1,
                "line_order": lo, "table_cell_precision": tpre, "table_cell_recall": trec,
                "table_structure": tstruct, "table_text_precision": ttext_prec,
                "table_text_recall": ttext_rec, "elapsed_s": r["elapsed_s"], "rss_mb": r["rss_mb"],
                "error": bool(r["error"]) or empty, "empty": empty, "chars": len(hyp),
                "key_number_hits": hits, "key_number_total": total,
            })
    df = pd.DataFrame(rows)
    page_csv = BENCH / (f"page_metrics{suffix}.csv" if suffix else "page_metrics.csv")
    df.to_csv(page_csv, index=False)
    # Average repeats at the page level first, so a page with three runs is not
    # counted as three independent pages.
    page_level = df.groupby(["engine", "key", "slug", "kind", "page"], as_index=False).agg(
        cer=("cer", "mean"), wer=("wer", "mean"),
        num_f1=("num_f1", "mean"), num_recall=("num_recall", "mean"),
        line_order=("line_order", "mean"),
        table_cell_recall=("table_cell_recall", "mean"),
        table_text_recall=("table_text_recall", "mean"),
        table_structure=("table_structure", "mean"),
        elapsed_s=("elapsed_s", "median"), rss_mb=("rss_mb", "max"),
        error=("error", "max"),
        key_number_hits=("key_number_hits", "mean"),
        key_number_total=("key_number_total", "mean"),
    )
    summary = (page_level.groupby("engine")
               .agg(pages=("page", "count"), cer=("cer", "mean"), wer=("wer", "mean"),
                    num_f1=("num_f1", "mean"), num_recall=("num_recall", "mean"),
                    line_order=("line_order", "mean"),
                    table_cell_recall=("table_cell_recall", "mean"),
                    table_text_recall=("table_text_recall", "mean"),
                    table_structure=("table_structure", "mean"),
                    median_s=("elapsed_s", "median"),
                    p95_s=("elapsed_s", lambda x: np.percentile(x, 95)),
                    peak_rss_mb=("rss_mb", "max"), failures=("error", "sum"))
               .reset_index())
    summary["key_number_recall"] = page_level.groupby("engine").apply(
        lambda g: g["key_number_hits"].sum() / max(1, g["key_number_total"].sum()),
        include_groups=False).values
    summary["n_runs"] = df.groupby("engine")["repeat"].nunique().values
    for metric in ("cer", "num_f1"):
        summary[f"{metric}_ci95"] = page_level.groupby("engine")[metric].apply(
            lambda s: (1.96 * s.std(ddof=1) / np.sqrt(len(s))) if len(s) > 1 else float("nan")
        ).values
    table_capable = {"docling", "mineru"}
    summary["rank_group"] = summary["engine"].map(
        lambda e: "table-capable" if e in table_capable else "text-only")
    base = (summary["num_f1"] * 0.45 + (1 - summary["cer"].clip(0, 1)) * 0.15 +
            (1 / (1 + summary["median_s"])) * 0.10)
    summary["rank_score"] = np.where(
        summary["engine"].isin(table_capable),
        base + summary["table_cell_recall"].fillna(0) * 0.30,
        base / 0.70,
    )
    summary = summary.sort_values("rank_score", ascending=False)
    summary_csv = BENCH / (f"engine_summary{suffix}.csv" if suffix else "engine_summary.csv")
    summary.to_csv(summary_csv, index=False)
    deg = degraded_metrics() if not suffix else pd.DataFrame()
    print(summary.to_string(index=False))
    if len(deg):
        print(deg.groupby("engine").agg(cer=("cer", "mean"), num_f1=("num_f1", "mean")).to_string())
    print("wrote", summary_csv, "pages", page_csv)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--suffix", default="",
                    help="e.g. _extended; reads results_*_extended.jsonl")
    args = ap.parse_args()
    main(args.manifest, args.suffix)
