"""Human review queue for fields that have no independent arithmetic check."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from . import config

DECISIONS = config.DATA / "review_decisions.json"
QUEUE_CSV = config.DATA / "review_queue.csv"
QUEUE_JSON = config.DATA / "review_queue.json"
VALID = {"verified", "rejected", "needs_review"}


def record_id(row: dict) -> str:
    key = "|".join(str(row.get(k, "")) for k in (
        "company", "document_type", "financial_year", "field_name",
        "source_document", "source_page",
    ))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def load_master() -> pd.DataFrame:
    return pd.read_csv(config.DATA / "master_dataset.csv")


def load_decisions() -> dict:
    if not DECISIONS.exists():
        return {}
    try:
        return json.loads(DECISIONS.read_text())
    except Exception:
        return {}


def save_decisions(decisions: dict) -> None:
    DECISIONS.write_text(json.dumps(decisions, indent=1))


def _priority(row: dict) -> int:
    if row.get("value_status") == "derived":
        return 0
    try:
        if float(row.get("confidence") or 0) < 0.85:
            return 1
    except Exception:
        pass
    return 2


def queue_df(master: pd.DataFrame | None = None) -> pd.DataFrame:
    df = load_master() if master is None else master.copy()
    df = df[df["validation_status"] == "needs_review"].copy()
    if "record_id" not in df:
        df["record_id"] = [record_id(r) for r in df.to_dict("records")]
    df["review_id"] = df["record_id"].where(df["record_id"].notna(), "")
    empty = df["review_id"].astype(str).isin(["", "nan", "None"])
    if empty.any():
        df.loc[empty, "review_id"] = [record_id(r) for r in df[empty].to_dict("records")]
    df["priority"] = [_priority(r) for r in df.to_dict("records")]
    cols = [c for c in [
        "review_id", "priority", "company", "document_type", "financial_year",
        "field_name", "normalized_value", "unit", "value_status", "confidence",
        "validation_status", "source_document", "source_page", "source_page_label",
        "source_text", "formula", "notes",
    ] if c in df]
    return df[cols].sort_values(["priority", "company", "field_name"]).reset_index(drop=True)


def export_queue() -> pd.DataFrame:
    q = queue_df()
    q.to_csv(QUEUE_CSV, index=False)
    QUEUE_JSON.write_text(json.dumps(q.to_dict(orient="records"), indent=1))
    print(f"review queue: {len(q)} fields -> {QUEUE_CSV}")
    print(q.groupby("company").size().sort_values(ascending=False).to_string())
    return q


def apply_decision(review_id: str, status: str, reviewer: str, note: str = "") -> dict:
    if status not in VALID:
        raise ValueError(f"status must be one of {sorted(VALID)}")
    decisions = load_decisions()
    decisions[review_id] = {
        "status": status, "reviewer": reviewer, "note": note,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_decisions(decisions)
    return decisions[review_id]


def apply_to_df(df: pd.DataFrame) -> pd.DataFrame:
    decisions = load_decisions()
    if not decisions:
        return df
    df = df.copy()
    ids = df.get("record_id")
    if ids is None:
        ids = pd.Series([record_id(r) for r in df.to_dict("records")], index=df.index)
    for idx, rid in ids.items():
        d = decisions.get(str(rid))
        if not d:
            continue
        df.at[idx, "validation_status"] = d["status"]
        df.at[idx, "reviewer"] = d.get("reviewer", "")
        df.at[idx, "reviewed_at"] = d.get("reviewed_at", "")
        if d.get("note"):
            old = str(df.at[idx, "notes"] or "")
            df.at[idx, "notes"] = (old + " | review: " + d["note"]).strip(" |")
    return df


def apply_to_rows(allrows: dict[str, list[dict]]) -> dict[str, list[dict]]:
    decisions = load_decisions()
    for rows in allrows.values():
        for r in rows:
            rid = r.get("record_id") or record_id(r)
            r["record_id"] = rid
            d = decisions.get(rid)
            if d:
                r["validation_status"] = d["status"]
                r["reviewer"] = d.get("reviewer", "")
                r["reviewed_at"] = d.get("reviewed_at", "")
                if d.get("note"):
                    r["notes"] = (str(r.get("notes") or "") + " | review: " + d["note"]).strip(" |")
    return allrows


def sync_master() -> int:
    df = load_master()
    if "record_id" not in df:
        df.insert(0, "record_id", [record_id(r) for r in df.to_dict("records")])
    df = apply_to_df(df)
    df.to_csv(config.DATA / "master_dataset.csv", index=False)
    df.to_parquet(config.DATA / "master_dataset.parquet", index=False)
    print(f"synced {len(load_decisions())} review decisions into master")
    return len(df)


def main():
    ap = argparse.ArgumentParser(description="Human review queue")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("queue", help="write review_queue.csv/json")
    p_list = sub.add_parser("list", help="print the queue")
    p_list.add_argument("--limit", type=int, default=20)
    p_apply = sub.add_parser("apply", help="record one decision")
    p_apply.add_argument("--id", required=True)
    p_apply.add_argument("--status", choices=sorted(VALID), required=True)
    p_apply.add_argument("--reviewer", required=True)
    p_apply.add_argument("--note", default="")
    sub.add_parser("sync", help="apply decisions to the master dataset")
    args = ap.parse_args()
    if args.cmd == "queue":
        export_queue()
    elif args.cmd == "list":
        print(queue_df().head(args.limit).to_string(index=False))
    elif args.cmd == "apply":
        print(apply_decision(args.id, args.status, args.reviewer, args.note))
    elif args.cmd == "sync":
        sync_master()


if __name__ == "__main__":
    main()
