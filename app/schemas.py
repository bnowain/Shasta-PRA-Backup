"""Pydantic response models for all API endpoints."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, field_validator


def _to_iso(date_str: str | None) -> str | None:
    """Convert MM/DD/YYYY to YYYY-MM-DD (ISO 8601)."""
    if not date_str:
        return date_str
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", date_str)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return date_str


# ── Request models ────────────────────────────────────────────────────────────

class RequestSummary(BaseModel):
    pretty_id: str
    request_state: Optional[str] = None
    request_text: Optional[str] = None
    department_names: Optional[str] = None
    poc_name: Optional[str] = None
    request_date: Optional[str] = None
    due_date: Optional[str] = None
    doc_count: int = 0

    @field_validator("request_date", "due_date", mode="before")
    @classmethod
    def _dates_to_iso(cls, v: str | None) -> str | None:
        return _to_iso(v)


class TimelineEventOut(BaseModel):
    timeline_id: int
    timeline_name: Optional[str] = None
    timeline_display_text: Optional[str] = None
    timeline_byline: Optional[str] = None
    timeline_icon_class: Optional[str] = None
    request_pretty_id: Optional[str] = None


class DocumentOut(BaseModel):
    id: int
    title: Optional[str] = None
    file_extension: Optional[str] = None
    file_size_mb: Optional[float] = None
    upload_date: Optional[str] = None
    downloaded: int = 0
    local_path: Optional[str] = None
    asset_url: Optional[str] = None
    request_pretty_id: Optional[str] = None

    @field_validator("upload_date", mode="before")
    @classmethod
    def _dates_to_iso(cls, v: str | None) -> str | None:
        return _to_iso(v)


class RequestDetail(BaseModel):
    pretty_id: str
    numeric_id: Optional[int] = None
    request_text: Optional[str] = None
    request_text_html: Optional[str] = None
    request_state: Optional[str] = None
    request_date: Optional[str] = None
    due_date: Optional[str] = None
    closed_date: Optional[str] = None
    department_names: Optional[str] = None
    poc_name: Optional[str] = None
    requester_name: Optional[str] = None
    requester_company: Optional[str] = None
    staff_cost: Optional[str] = None
    request_staff_hours: Optional[str] = None
    page_url: Optional[str] = None
    timeline: list[TimelineEventOut] = []
    documents: list[DocumentOut] = []

    @field_validator("request_date", "due_date", "closed_date", mode="before")
    @classmethod
    def _dates_to_iso(cls, v: str | None) -> str | None:
        return _to_iso(v)


# ── Department models ─────────────────────────────────────────────────────────

class DepartmentOut(BaseModel):
    id: int
    name: Optional[str] = None
    request_count: int = 0


# ── Search models ─────────────────────────────────────────────────────────────

class SearchResults(BaseModel):
    requests: list[RequestSummary] = []
    timeline_events: list[TimelineEventOut] = []
    documents: list[DocumentOut] = []


# ── Stats models ──────────────────────────────────────────────────────────────

class StatusBreakdown(BaseModel):
    status: str
    count: int


class DepartmentBreakdown(BaseModel):
    department: str
    count: int


class MonthCount(BaseModel):
    month: str
    count: int


class StatsOut(BaseModel):
    total_requests: int = 0
    total_documents: int = 0
    total_departments: int = 0
    status_breakdown: list[StatusBreakdown] = []
    department_breakdown: list[DepartmentBreakdown] = []
    requests_by_month: list[MonthCount] = []


# ── Transcription models ─────────────────────────────────────────────────────

class TranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0


class TranscriptionResult(BaseModel):
    document_id: int
    text: str
    segments: list[TranscriptionSegment] = []
    duration_seconds: Optional[float] = None
    processing_seconds: Optional[float] = None
    method: str = "whisper"
    created_at: Optional[str] = None


class TranscriptionStatus(BaseModel):
    total_transcribable: int = 0
    transcribed: int = 0
    pending: int = 0
    failed: int = 0


# ── Text extraction models ──────────────────────────────────────────────────

class ExtractedTextPage(BaseModel):
    page_number: int
    text: str
    method: str


class ExtractedTextResult(BaseModel):
    document_id: int
    pages: list[ExtractedTextPage] = []
    total_pages: int = 0
    total_chars: int = 0
    method: str = ""
    created_at: Optional[str] = None


class TextExtractionStatus(BaseModel):
    total_extractable: int = 0
    extracted: int = 0
    pending: int = 0
    failed: int = 0
    total_pages: int = 0


# ── Email message model ────────────────────────────────────────────────────

class EmailMessage(BaseModel):
    document_id: int
    sender: str = ""
    to: str = ""
    cc: str = ""
    subject: str = ""
    date: str = ""
    body_html: str = ""
    body_text: str = ""
