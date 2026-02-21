"""Full-text search across all PRA tables."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app import schemas

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=schemas.SearchResults)
def search_all(
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(20, ge=1, le=100),
    conn: Connection = Depends(get_db),
):
    pattern = f"%{q}%"

    # Search requests
    req_rows = conn.execute(text("""
        SELECT r.pretty_id, r.request_state, substr(r.request_text, 1, 200) AS request_text,
               r.department_names, r.poc_name, r.request_date, r.due_date,
               (SELECT COUNT(*) FROM documents d WHERE d.request_pretty_id = r.pretty_id) AS doc_count
        FROM requests r
        WHERE r.request_text LIKE :q OR r.pretty_id LIKE :q
              OR r.requester_name LIKE :q OR r.poc_name LIKE :q
              OR r.department_names LIKE :q
        ORDER BY substr(r.request_date,7,4)||substr(r.request_date,1,2)||substr(r.request_date,4,2) DESC
        LIMIT :limit
    """), {"q": pattern, "limit": limit}).mappings().all()

    # Search timeline events
    tl_rows = conn.execute(text("""
        SELECT timeline_id, timeline_name, timeline_display_text,
               timeline_byline, timeline_icon_class, request_pretty_id
        FROM timeline_events
        WHERE timeline_display_text LIKE :q OR timeline_byline LIKE :q
        LIMIT :limit
    """), {"q": pattern, "limit": limit}).mappings().all()

    # Search documents
    doc_rows = conn.execute(text("""
        SELECT id, title, file_extension, file_size_mb, upload_date,
               downloaded, local_path, asset_url, request_pretty_id
        FROM documents
        WHERE title LIKE :q
        LIMIT :limit
    """), {"q": pattern, "limit": limit}).mappings().all()

    return schemas.SearchResults(
        requests=[schemas.RequestSummary(**dict(r)) for r in req_rows],
        timeline_events=[schemas.TimelineEventOut(**dict(t)) for t in tl_rows],
        documents=[schemas.DocumentOut(**dict(d)) for d in doc_rows],
    )
