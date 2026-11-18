-- PostgreSQL schema for the document intelligence pipeline.
CREATE TABLE IF NOT EXISTS companies (
    id            SERIAL PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    sector        TEXT,
    kind          TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    company_id    INTEGER REFERENCES companies(id),
    doc_type      TEXT NOT NULL,
    title         TEXT,
    period        TEXT,
    url           TEXT,
    download_date DATE,
    file_path     TEXT,
    sha256        CHAR(64) UNIQUE,
    pages         INTEGER,
    digital_pages INTEGER,
    scanned_pages INTEGER,
    status        TEXT DEFAULT 'downloaded'
);

CREATE TABLE IF NOT EXISTS extracted_fields (
    id                BIGSERIAL PRIMARY KEY,
    document_id       BIGINT REFERENCES documents(id),
    company           TEXT NOT NULL,
    document_type     TEXT NOT NULL,
    financial_year    TEXT,
    report_period     TEXT,
    reporting_basis   TEXT,
    field_name        TEXT NOT NULL,
    original_value    TEXT,
    normalized_value  DOUBLE PRECISION,
    currency          TEXT,
    unit              TEXT,
    source_value      DOUBLE PRECISION,
    source_unit       TEXT,
    scale_factor      DOUBLE PRECISION,
    value_status      TEXT DEFAULT 'reported',
    is_derived        BOOLEAN DEFAULT FALSE,
    formula           TEXT,
    source_page       INTEGER,
    source_page_label TEXT,
    source_table      TEXT,
    source_text       TEXT,
    source_bbox       JSONB,
    source_sha256     TEXT,
    confidence        DOUBLE PRECISION,
    confidence_method TEXT,
    validation_status TEXT,
    extraction_engine TEXT,
    model_version     TEXT,
    section           TEXT,
    notes             TEXT,
    run_id            TEXT,
    extracted_at      TIMESTAMPTZ DEFAULT now(),
    reviewer          TEXT,
    reviewed_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fields_company ON extracted_fields(company);
CREATE INDEX IF NOT EXISTS idx_fields_name ON extracted_fields(field_name);
CREATE INDEX IF NOT EXISTS idx_fields_period ON extracted_fields(financial_year, report_period);
CREATE INDEX IF NOT EXISTS idx_fields_status ON extracted_fields(value_status, validation_status);
CREATE INDEX IF NOT EXISTS idx_fields_run ON extracted_fields(run_id);

CREATE TABLE IF NOT EXISTS extractor_runs (
    id            BIGSERIAL PRIMARY KEY,
    run_id        TEXT UNIQUE NOT NULL,
    started_at    TIMESTAMPTZ DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    git_commit    TEXT,
    config        JSONB,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS benchmark_results (
    id          BIGSERIAL PRIMARY KEY,
    engine      TEXT NOT NULL,
    page_key    TEXT NOT NULL,
    cer         DOUBLE PRECISION,
    wer         DOUBLE PRECISION,
    num_f1      DOUBLE PRECISION,
    table_recall DOUBLE PRECISION,
    table_structure DOUBLE PRECISION,
    elapsed_s   DOUBLE PRECISION,
    peak_rss_mb DOUBLE PRECISION,
    error       BOOLEAN,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS validation_runs (
    id           BIGSERIAL PRIMARY KEY,
    company      TEXT,
    checks       JSONB,
    passed       INTEGER,
    total        INTEGER,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- Convenience view: one row per company/period/field with provenance.
CREATE OR REPLACE VIEW v_financials AS
SELECT company, document_type, financial_year, report_period, reporting_basis,
       field_name, normalized_value, unit, currency, source_page, source_page_label,
       source_table, source_text, source_value, source_unit, scale_factor,
       value_status, is_derived, formula, validation_status, extraction_engine, run_id
FROM extracted_fields;
