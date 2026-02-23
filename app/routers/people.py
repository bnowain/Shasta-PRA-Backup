"""People router — person CRUD and Atlas integration for PRA."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.database import get_db

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("")
def list_people(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    conn=Depends(get_db),
):
    """List/search people."""
    if search:
        rows = conn.execute(
            text("""
                SELECT p.id, p.canonical_name, p.aliases, p.role, p.created_at,
                       COUNT(rp.id) AS request_count
                FROM people p
                LEFT JOIN request_people rp ON rp.person_id = p.id
                WHERE p.canonical_name LIKE :pattern
                   OR p.aliases LIKE :pattern
                GROUP BY p.id
                ORDER BY p.canonical_name
                LIMIT :limit
            """),
            {"pattern": f"%{search}%", "limit": limit},
        ).fetchall()
    else:
        rows = conn.execute(
            text("""
                SELECT p.id, p.canonical_name, p.aliases, p.role, p.created_at,
                       COUNT(rp.id) AS request_count
                FROM people p
                LEFT JOIN request_people rp ON rp.person_id = p.id
                GROUP BY p.id
                ORDER BY p.canonical_name
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

    return [
        {
            "id": r.id,
            "canonical_name": r.canonical_name,
            "aliases": r.aliases,
            "role": r.role,
            "created_at": r.created_at,
            "request_count": r.request_count,
        }
        for r in rows
    ]


@router.get("/{person_id}")
def get_person(person_id: int, conn=Depends(get_db)):
    """Get person detail with linked requests."""
    person = conn.execute(
        text("SELECT * FROM people WHERE id = :id"),
        {"id": person_id},
    ).fetchone()
    if not person:
        return {"error": "Person not found"}

    links = conn.execute(
        text("""
            SELECT rp.request_pretty_id, rp.role, rp.source,
                   r.request_text, r.request_state, r.request_date
            FROM request_people rp
            JOIN requests r ON r.pretty_id = rp.request_pretty_id
            WHERE rp.person_id = :pid
            ORDER BY r.request_date DESC
        """),
        {"pid": person_id},
    ).fetchall()

    return {
        "id": person.id,
        "canonical_name": person.canonical_name,
        "aliases": person.aliases,
        "role": person.role,
        "created_at": person.created_at,
        "requests": [
            {
                "pretty_id": l.request_pretty_id,
                "role": l.role,
                "source": l.source,
                "request_text": (l.request_text or "")[:200],
                "request_state": l.request_state,
                "request_date": l.request_date,
            }
            for l in links
        ],
    }


@router.post("")
def create_person(
    canonical_name: str = Query(...),
    role: str = Query(""),
    aliases: str = Query(""),
    conn=Depends(get_db),
):
    """Create a new person."""
    conn.execute(
        text("INSERT INTO people (canonical_name, aliases, role) VALUES (:name, :aliases, :role)"),
        {"name": canonical_name, "aliases": aliases, "role": role},
    )
    conn.commit()
    person = conn.execute(
        text("SELECT * FROM people WHERE canonical_name = :name"),
        {"name": canonical_name},
    ).fetchone()
    return {"id": person.id, "canonical_name": person.canonical_name}


@router.post("/link")
def link_person_to_request(
    person_id: int = Query(...),
    request_pretty_id: str = Query(...),
    role: str = Query("requester"),
    source: str = Query("manual"),
    conn=Depends(get_db),
):
    """Link a person to a PRA request."""
    conn.execute(
        text("""
            INSERT OR IGNORE INTO request_people (request_pretty_id, person_id, role, source)
            VALUES (:rid, :pid, :role, :source)
        """),
        {"rid": request_pretty_id, "pid": person_id, "role": role, "source": source},
    )
    conn.commit()
    return {"status": "linked"}
