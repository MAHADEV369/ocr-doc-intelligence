"""Pydantic contracts for every extracted field and document record."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DocType(str, Enum):
    annual_report = "annual_report"
    quarterly_results = "quarterly_results"
    investor_presentation = "investor_presentation"


class ReportingBasis(str, Enum):
    consolidated = "consolidated"
    standalone = "standalone"
    unknown = "unknown"


class ValidationStatus(str, Enum):
    verified = "verified"
    arithmetic_ok = "arithmetic_ok"
    needs_review = "needs_review"
    failed = "failed"
    not_applicable = "not_applicable"


class ValueStatus(str, Enum):
    reported = "reported"
    derived = "derived"
    nil = "nil"
    not_reported = "not_reported"
    not_extractable = "not_extractable"


class DocumentRecord(BaseModel):
    company: str
    slug: str
    doc_type: DocType
    title: str
    period: str
    url: str
    download_date: date
    file: str
    sha256: str
    pages: int = Field(ge=0)
    status: str = "downloaded"


class ExtractedField(BaseModel):
    """Illustrative contract from the mission brief, extended for provenance."""

    record_id: str = ""
    company: str
    document_type: str
    financial_year: str = ""
    report_period: str = ""  # kept as report_period because pydantic reserves model_*
    reporting_basis: ReportingBasis = ReportingBasis.unknown
    field_name: str
    original_value: str = ""
    normalized_value: Optional[float] = None
    currency: Optional[str] = "INR"
    unit: Optional[str] = None
    source_document: str = ""
    source_page: Optional[int] = None
    source_page_label: Optional[str] = None
    source_table: Optional[str] = None
    source_text: str = ""
    source_bbox: Optional[list[float]] = None
    source_sha256: Optional[str] = None
    source_value: Optional[float] = None
    source_unit: Optional[str] = None
    scale_factor: Optional[float] = None
    value_status: ValueStatus = ValueStatus.reported
    is_derived: bool = False
    formula: str = ""
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    confidence_method: str = ""
    validation_status: ValidationStatus = ValidationStatus.needs_review
    extraction_engine: str = ""
    model_version: str = ""
    section: str = ""
    notes: str = ""
    run_id: str = ""
    extracted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewer: str = ""
    reviewed_at: str = ""

    @field_validator("normalized_value", "source_value")
    @classmethod
    def finite(cls, v):
        if v is not None and (v != v or abs(v) == float("inf")):
            raise ValueError("value must be finite")
        return v

    @field_validator("scale_factor")
    @classmethod
    def finite_scale(cls, v):
        if v is not None and (v != v or abs(v) == float("inf") or v == 0):
            raise ValueError("scale_factor must be non-zero and finite")
        return v


class PageProfile(BaseModel):
    page: int
    chars: int
    words: int
    images: int
    kind: str  # digital | scanned | mixed | blank
    has_tables: bool = False
    route: str = ""
    route_reason: str = ""
    quality_score: float = 0.0
    image_coverage: float = 0.0


class DocumentProfile(BaseModel):
    file: str
    sha256: str
    pages: int
    digital_pages: int
    scanned_pages: int
    mixed_pages: int
    blank_pages: int
    page_profiles: list[PageProfile]
    native_chars_total: int
    is_scanned_majority: bool
