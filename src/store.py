"""Optional PostgreSQL + MinIO persistence.

The local CSV/JSON files remain the source of truth for the benchmark. When
DATABASE_URL and S3_ENDPOINT are set, the same records are mirrored into the
production stores described in the architecture report.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_BUCKET = os.getenv("S3_BUCKET", "docintel")


def enabled() -> bool:
    return bool(DATABASE_URL)


def connect():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def ensure_schema() -> None:
    schema = (config.ROOT / "db" / "schema.sql").read_text()
    with connect() as con, con.cursor() as cur:
        cur.execute(schema)
    con.close()


def sync_documents() -> int:
    n = 0
    with connect() as con, con.cursor() as cur:
        for mpath in sorted(config.MANIFESTS.glob("*.json")):
            m = json.loads(mpath.read_text())
            cur.execute(
                """INSERT INTO companies (slug, name, sector, kind)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name,
                   sector=EXCLUDED.sector, kind=EXCLUDED.kind""",
                (m["slug"], m.get("company", m["slug"]), m.get("sector"), m.get("kind")),
            )
            for d in m.get("documents", []):
                cur.execute(
                    """INSERT INTO documents
                       (company_id, doc_type, title, period, url, download_date, file_path,
                        sha256, pages, status)
                       VALUES ((SELECT id FROM companies WHERE slug=%s), %s, %s, %s, %s,
                               %s, %s, %s, %s, %s)
                       ON CONFLICT (sha256) DO UPDATE SET pages=EXCLUDED.pages,
                       status=EXCLUDED.status""",
                    (m["slug"], d.get("doc_type"), d.get("title"), d.get("period"),
                     d.get("url"), d.get("download_date"), d.get("file"), d.get("sha256"),
                     d.get("pages", 0), d.get("status", "downloaded")),
                )
                n += 1
    con.close()
    return n


def sync_fields(df: pd.DataFrame) -> int:
    cols = ["company", "document_type", "financial_year", "report_period", "reporting_basis",
            "field_name", "original_value", "normalized_value", "currency", "unit",
            "source_value", "source_unit", "scale_factor", "value_status", "is_derived", "formula",
            "source_page", "source_page_label", "source_table", "source_text", "source_sha256",
            "confidence", "confidence_method", "validation_status",
            "extraction_engine", "model_version", "section", "notes", "run_id"]
    d = df.copy()
    for c in cols:
        if c not in d:
            d[c] = None
    rows = d[cols].astype(object).where(pd.notna(d[cols]), None).to_dict(orient="records")
    with connect() as con, con.cursor() as cur:
        run_id = next((r["run_id"] for r in rows if r.get("run_id")), None)
        if run_id:
            cur.execute("DELETE FROM extracted_fields WHERE run_id=%s", (run_id,))
        for r in rows:
            cur.execute(
                """INSERT INTO extracted_fields
                   (company, document_type, financial_year, report_period, reporting_basis,
                    field_name, original_value, normalized_value, currency, unit,
                    source_value, source_unit, scale_factor, value_status, is_derived, formula,
                    source_page, source_page_label, source_table, source_text, source_sha256,
                    confidence, confidence_method, validation_status, extraction_engine,
                    model_version, section, notes, run_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s,%s,%s,%s,%s)""",
                (r["company"], r["document_type"], r["financial_year"], r["report_period"],
                 r["reporting_basis"], r["field_name"], r["original_value"], r["normalized_value"],
                 r["currency"], r["unit"], r["source_value"], r["source_unit"], r["scale_factor"],
                 r["value_status"], r["is_derived"], r["formula"], r["source_page"],
                 r["source_page_label"], r["source_table"], r["source_text"], r["source_sha256"],
                 r["confidence"], r["confidence_method"], r["validation_status"],
                 r["extraction_engine"], r["model_version"], r["section"], r["notes"], r["run_id"]),
            )
    con.close()
    return len(rows)


def upload_file(path: Path, key: str | None = None) -> str | None:
    if not S3_ENDPOINT:
        return None
    import boto3
    s3 = boto3.client(
        "s3", endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY, aws_secret_access_key=S3_SECRET_KEY,
    )
    key = key or Path(path).name
    s3.upload_file(str(path), S3_BUCKET, key)
    return key


def sync_all() -> dict:
    if not enabled():
        return {"enabled": False, "documents": 0, "fields": 0}
    ensure_schema()
    docs = sync_documents()
    fields = sync_fields(pd.read_csv(config.DATA / "master_dataset.csv"))
    uploads = []
    if S3_ENDPOINT:
        for p in [config.DATA / "master_dataset.csv", config.DATA / "master_dataset.parquet",
                  config.DATA / "coverage_matrix.csv", config.BENCHMARK / "engine_summary.csv"]:
            if p.exists():
                uploads.append(upload_file(p, f"exports/{p.name}"))
    return {"enabled": True, "documents": docs, "fields": fields, "uploads": uploads}


if __name__ == "__main__":
    print(sync_all())
