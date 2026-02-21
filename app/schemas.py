"""Pydantic response models for all API endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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


class TimelineEventOut(BaseModel):
    timeline_id: int
    timeline_name: Optional[str] = None
    timeline_display_text: Optional[str] = None
    timeline_byline: Optional[str] = None
    timeline_icon_class: Optional[str] = None


class DocumentOut(BaseModel):
    id: int
    title: Optional[str] = None
    file_extension: Optional[str] = None
    file_size_mb: Optional[float] = None
    upload_date: Optional[str] = None
    downloaded: int = 0
    local_path: Optional[str] = None
    asset_url: Optional[str] = None


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
