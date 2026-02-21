"""Statistics endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app import schemas

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=schemas.StatsOut)
def get_stats(conn: Connection = Depends(get_db)):
    total_requests = conn.execute(text("SELECT COUNT(*) FROM requests")).scalar()
    total_documents = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar()
    total_departments = conn.execute(text("SELECT COUNT(*) FROM departments")).scalar()

    # Status breakdown
    status_rows = conn.execute(text("""
        SELECT request_state AS status, COUNT(*) AS count
        FROM requests
        WHERE request_state IS NOT NULL AND request_state != ''
        GROUP BY request_state
        ORDER BY count DESC
    """)).mappings().all()

    # Department breakdown
    dept_rows = conn.execute(text("""
        SELECT d.name AS department,
               (SELECT COUNT(*) FROM requests r
                WHERE r.department_names LIKE '%' || d.name || '%') AS count
        FROM departments d
        ORDER BY count DESC
        LIMIT 20
    """)).mappings().all()

    # Requests by month (MM/DD/YYYY → YYYY-MM)
    month_rows = conn.execute(text("""
        SELECT substr(request_date,7,4) || '-' || substr(request_date,1,2) AS month,
               COUNT(*) AS count
        FROM requests
        WHERE request_date IS NOT NULL AND length(request_date) >= 10
        GROUP BY month
        ORDER BY month
    """)).mappings().all()

    return schemas.StatsOut(
        total_requests=total_requests,
        total_documents=total_documents,
        total_departments=total_departments,
        status_breakdown=[schemas.StatusBreakdown(**dict(r)) for r in status_rows],
        department_breakdown=[schemas.DepartmentBreakdown(**dict(r)) for r in dept_rows],
        requests_by_month=[schemas.MonthCount(**dict(r)) for r in month_rows],
    )
