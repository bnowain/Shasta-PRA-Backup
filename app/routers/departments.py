"""Department endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app import schemas

router = APIRouter(prefix="/api/departments", tags=["departments"])


@router.get("", response_model=list[schemas.DepartmentOut])
def list_departments(conn: Connection = Depends(get_db)):
    rows = conn.execute(text("""
        SELECT d.id, d.name,
               (SELECT COUNT(*) FROM requests r
                WHERE r.department_names LIKE '%' || d.name || '%') AS request_count
        FROM departments d
        ORDER BY request_count DESC
    """)).mappings().all()
    return [schemas.DepartmentOut(**dict(r)) for r in rows]


@router.get("/{dept_id}/requests", response_model=dict)
def department_requests(
    dept_id: int,
    sort: str = Query("newest"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_db),
):
    # Get department name
    dept = conn.execute(
        text("SELECT name FROM departments WHERE id = :did"),
        {"did": dept_id},
    ).mappings().first()
    if not dept:
        raise HTTPException(404, "Department not found")
    dept_name = dict(dept)["name"]

    order_map = {
        "newest": "substr(r.request_date,7,4)||substr(r.request_date,1,2)||substr(r.request_date,4,2) DESC",
        "oldest": "substr(r.request_date,7,4)||substr(r.request_date,1,2)||substr(r.request_date,4,2) ASC",
        "id": "r.pretty_id DESC",
    }
    order = order_map.get(sort, order_map["newest"])

    where = "r.department_names LIKE '%' || :dept_name || '%'"
    params: dict = {"dept_name": dept_name}

    total = conn.execute(
        text(f"SELECT COUNT(*) FROM requests r WHERE {where}"), params
    ).scalar()

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

    return {
        "department": dept_name,
        "total": total,
        "results": [schemas.RequestSummary(**dict(r)) for r in rows],
    }
