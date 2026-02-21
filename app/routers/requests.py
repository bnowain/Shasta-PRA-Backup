"""PRA request endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app import schemas

router = APIRouter(prefix="/api/requests", tags=["requests"])


def _build_request_query(
    q: Optional[str] = None,
    status: Optional[str] = None,
    department: Optional[str] = None,
    poc: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Build WHERE clauses and params for request filtering."""
    clauses = []
    params: dict = {}

    if q:
        clauses.append(
            "(r.request_text LIKE :q OR r.pretty_id LIKE :q_exact"
            " OR r.requester_name LIKE :q OR r.poc_name LIKE :q)"
        )
        params["q"] = f"%{q}%"
        params["q_exact"] = f"%{q}%"

    if status:
        clauses.append("r.request_state = :status")
        params["status"] = status

    if department:
        clauses.append("r.department_names LIKE :dept")
        params["dept"] = f"%{department}%"

    if poc:
        clauses.append("r.poc_name LIKE :poc")
        params["poc"] = f"%{poc}%"

    if date_from:
        # request_date is MM/DD/YYYY — rearrange for comparison
        clauses.append(
            "substr(r.request_date,7,4)||substr(r.request_date,1,2)||substr(r.request_date,4,2) >= :date_from"
        )
        params["date_from"] = date_from.replace("-", "")

    if date_to:
        clauses.append(
            "substr(r.request_date,7,4)||substr(r.request_date,1,2)||substr(r.request_date,4,2) <= :date_to"
        )
        params["date_to"] = date_to.replace("-", "")

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


@router.get("", response_model=dict)
def list_requests(
    q: Optional[str] = Query(None, description="Search text"),
    status: Optional[str] = Query(None, description="Filter by request_state"),
    department: Optional[str] = Query(None, description="Filter by department name"),
    poc: Optional[str] = Query(None, description="Filter by POC name"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    sort: str = Query("newest", description="Sort: newest, oldest, id"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_db),
):
    where, params = _build_request_query(q, status, department, poc, date_from, date_to)

    order_map = {
        "newest": "substr(r.request_date,7,4)||substr(r.request_date,1,2)||substr(r.request_date,4,2) DESC",
        "oldest": "substr(r.request_date,7,4)||substr(r.request_date,1,2)||substr(r.request_date,4,2) ASC",
        "id": "r.pretty_id DESC",
    }
    order = order_map.get(sort, order_map["newest"])

    # Count
    count_sql = f"SELECT COUNT(*) FROM requests r WHERE {where}"
    total = conn.execute(text(count_sql), params).scalar()

    # Results
    sql = f"""
        SELECT r.pretty_id, r.request_state, substr(r.request_text, 1, 200) AS request_text,
               r.department_names, r.poc_name, r.request_date, r.due_date,
               (SELECT COUNT(*) FROM documents d WHERE d.request_pretty_id = r.pretty_id) AS doc_count
        FROM requests r
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = limit
    params["offset"] = offset
    rows = conn.execute(text(sql), params).mappings().all()

    results = [schemas.RequestSummary(**dict(r)) for r in rows]
    return {"total": total, "results": results}


@router.get("/{pretty_id}", response_model=schemas.RequestDetail)
def get_request(pretty_id: str, conn: Connection = Depends(get_db)):
    # Main request
    row = conn.execute(
        text("SELECT * FROM requests WHERE pretty_id = :pid"),
        {"pid": pretty_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Request not found")

    r = dict(row)

    # Timeline
    tl_rows = conn.execute(
        text("""SELECT timeline_id, timeline_name, timeline_display_text,
                       timeline_byline, timeline_icon_class
                FROM timeline_events WHERE request_pretty_id = :pid
                ORDER BY timeline_id"""),
        {"pid": pretty_id},
    ).mappings().all()

    # Documents
    doc_rows = conn.execute(
        text("""SELECT id, title, file_extension, file_size_mb, upload_date,
                       downloaded, local_path, asset_url
                FROM documents WHERE request_pretty_id = :pid
                ORDER BY id"""),
        {"pid": pretty_id},
    ).mappings().all()

    return schemas.RequestDetail(
        pretty_id=r["pretty_id"],
        numeric_id=r.get("numeric_id"),
        request_text=r.get("request_text"),
        request_text_html=r.get("request_text_html"),
        request_state=r.get("request_state"),
        request_date=r.get("request_date"),
        due_date=r.get("due_date"),
        closed_date=r.get("closed_date"),
        department_names=r.get("department_names"),
        poc_name=r.get("poc_name"),
        requester_name=r.get("requester_name"),
        requester_company=r.get("requester_company"),
        staff_cost=r.get("staff_cost"),
        request_staff_hours=r.get("request_staff_hours"),
        page_url=r.get("page_url"),
        timeline=[schemas.TimelineEventOut(**dict(t)) for t in tl_rows],
        documents=[schemas.DocumentOut(**dict(d)) for d in doc_rows],
    )
