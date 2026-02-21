"""Document file serving, listing, and preview conversion."""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.config import BASE_DIR, DOCS_DIR, SOFFICE_PATH, CONVERTIBLE_EXTENSIONS
from app.database import get_db
from app import schemas

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Types that browsers can display natively
_INLINE_TYPES = {"pdf", "jpg", "jpeg", "png", "gif", "webp", "bmp",
                 "mp4", "webm", "mp3", "m4a", "wav", "ogg", "txt", "csv"}

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain",
    "csv": "text/csv",
}


def _resolve_doc_path(doc: dict) -> Path:
    """Resolve and validate a document's file path."""
    if not doc["downloaded"] or not doc["local_path"]:
        raise HTTPException(404, "Document file not available (metadata only)")

    file_path = Path(doc["local_path"])
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    try:
        resolved = file_path.resolve()
        docs_resolved = DOCS_DIR.resolve()
        if not str(resolved).startswith(str(docs_resolved)):
            raise HTTPException(403, "Access denied")
    except (OSError, ValueError):
        raise HTTPException(400, "Invalid file path")

    if not resolved.exists():
        raise HTTPException(404, "File not found on disk")

    return resolved


# ── List documents ────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
def list_documents(
    q: Optional[str] = Query(None, description="Search title"),
    ext: Optional[str] = Query(None, description="Filter by file extension"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    sort: str = Query("newest", description="Sort: newest, oldest, title, size"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(get_db),
):
    clauses = []
    params: dict = {}

    if q:
        clauses.append("d.title LIKE :q")
        params["q"] = f"%{q}%"

    if ext:
        clauses.append("LOWER(d.file_extension) = :ext")
        params["ext"] = ext.lower()

    if date_from:
        clauses.append(
            "substr(d.upload_date,7,4)||substr(d.upload_date,1,2)||substr(d.upload_date,4,2) >= :date_from"
        )
        params["date_from"] = date_from.replace("-", "")

    if date_to:
        clauses.append(
            "substr(d.upload_date,7,4)||substr(d.upload_date,1,2)||substr(d.upload_date,4,2) <= :date_to"
        )
        params["date_to"] = date_to.replace("-", "")

    where = " AND ".join(clauses) if clauses else "1=1"

    order_map = {
        "newest": "substr(d.upload_date,7,4)||substr(d.upload_date,1,2)||substr(d.upload_date,4,2) DESC",
        "oldest": "substr(d.upload_date,7,4)||substr(d.upload_date,1,2)||substr(d.upload_date,4,2) ASC",
        "title": "d.title ASC",
        "size": "d.file_size_mb DESC",
    }
    order = order_map.get(sort, order_map["newest"])

    total = conn.execute(text(f"SELECT COUNT(*) FROM documents d WHERE {where}"), params).scalar()

    sql = f"""
        SELECT d.id, d.title, d.file_extension, d.file_size_mb, d.upload_date,
               d.downloaded, d.local_path, d.asset_url, d.request_pretty_id
        FROM documents d
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = limit
    params["offset"] = offset
    rows = conn.execute(text(sql), params).mappings().all()

    return {
        "total": total,
        "results": [schemas.DocumentOut(**dict(r)) for r in rows],
    }


# ── File type extensions list ─────────────────────────────────────────────────

@router.get("/extensions", tags=["documents"])
def list_extensions(conn: Connection = Depends(get_db)):
    rows = conn.execute(text("""
        SELECT LOWER(file_extension) AS ext, COUNT(*) AS cnt
        FROM documents
        WHERE file_extension IS NOT NULL AND file_extension != ''
        GROUP BY LOWER(file_extension)
        ORDER BY cnt DESC
    """)).mappings().all()
    return [{"ext": r["ext"], "count": r["cnt"]} for r in rows]


# ── Preview endpoint (with LibreOffice conversion) ────────────────────────────

@router.get("/{doc_id}/preview")
def preview_document(doc_id: int, conn: Connection = Depends(get_db)):
    row = conn.execute(
        text("SELECT local_path, title, file_extension, downloaded FROM documents WHERE id = :did"),
        {"did": doc_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Document not found")

    doc = dict(row)
    ext = (doc.get("file_extension") or "").lower()

    # Native-previewable types — serve directly
    if ext in _INLINE_TYPES:
        resolved = _resolve_doc_path(doc)
        media_type = _MEDIA_TYPES.get(ext, "application/octet-stream")
        return FileResponse(str(resolved), media_type=media_type)

    # Office types — convert to PDF via LibreOffice
    if ext in CONVERTIBLE_EXTENSIONS:
        resolved = _resolve_doc_path(doc)
        cache_path = resolved.parent / (resolved.name + ".preview.pdf")

        if cache_path.exists():
            return FileResponse(str(cache_path), media_type="application/pdf")

        # Convert using LibreOffice headless
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    [SOFFICE_PATH, "--headless", "--convert-to", "pdf",
                     "--outdir", tmpdir, str(resolved)],
                    capture_output=True, timeout=60,
                )
                if result.returncode != 0:
                    raise HTTPException(
                        500,
                        f"LibreOffice conversion failed: {result.stderr.decode(errors='replace')[:200]}"
                    )

                # Find the output PDF in temp dir
                tmp_path = Path(tmpdir)
                pdf_files = list(tmp_path.glob("*.pdf"))
                if not pdf_files:
                    raise HTTPException(500, "Conversion produced no PDF output")

                # Move to cache location
                pdf_files[0].replace(cache_path)

        except FileNotFoundError:
            raise HTTPException(
                501,
                "LibreOffice not installed. Install it to preview Office documents."
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Conversion timed out")

        return FileResponse(str(cache_path), media_type="application/pdf")

    # Not previewable
    raise HTTPException(
        415,
        f"Preview not available for .{ext} files"
    )


# ── Original file serving ─────────────────────────────────────────────────────

@router.get("/{doc_id}/file")
def serve_document(doc_id: int, conn: Connection = Depends(get_db)):
    row = conn.execute(
        text("SELECT local_path, title, file_extension, downloaded FROM documents WHERE id = :did"),
        {"did": doc_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Document not found")

    doc = dict(row)
    resolved = _resolve_doc_path(doc)
    ext = (doc.get("file_extension") or "").lower()
    media_type = _MEDIA_TYPES.get(ext, "application/octet-stream")

    # Viewable types: serve inline
    if ext in _INLINE_TYPES:
        return FileResponse(str(resolved), media_type=media_type)

    # Everything else: serve as download
    filename = doc.get("title") or f"document_{doc_id}"
    if ext and not filename.endswith(f".{ext}"):
        filename = f"{filename}.{ext}"
    return FileResponse(str(resolved), media_type=media_type, filename=filename)
