"""Document file serving, listing, and preview conversion."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.config import (BASE_DIR, DOCS_DIR, SOFFICE_PATH, CONVERTIBLE_EXTENSIONS,
                        TRANSCRIBABLE_EXTENSIONS, TEXT_EXTRACTABLE_EXTENSIONS,
                        DIRECT_READ_EXTENSIONS)
from app.database import get_db
from app import schemas

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Types that browsers can display natively
_INLINE_TYPES = {"pdf", "jpg", "jpeg", "png", "gif", "webp", "bmp",
                 "mp4", "webm", "mp3", "m4a", "wav", "ogg", "txt", "csv",
                 "html", "msg", "xlsx", "xls"}

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
    "html": "text/html",
    "msg": "application/vnd.ms-outlook",
}

# Max file size for on-demand conversion (50 MB)
_MAX_ONDEMAND_MB = 50


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


def convert_to_pdf(source: Path, cache_path: Path, timeout: int = 120) -> bool:
    """Convert a document to PDF using LibreOffice headless.

    Returns True on success, False on failure. Raises FileNotFoundError
    if LibreOffice is not installed.
    """
    if cache_path.exists():
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [SOFFICE_PATH, "--headless", "--convert-to", "pdf",
             "--outdir", tmpdir, str(source)],
            capture_output=True, timeout=timeout,
        )
        if result.returncode != 0:
            return False

        tmp_path = Path(tmpdir)
        pdf_files = list(tmp_path.glob("*.pdf"))
        if not pdf_files:
            return False

        shutil.copy2(str(pdf_files[0]), str(cache_path))

    return True


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


# ── Text extraction status ────────────────────────────────────────────────────

@router.get("/text-extraction-status", response_model=schemas.TextExtractionStatus)
def text_extraction_status(conn: Connection = Depends(get_db)):
    all_exts = TEXT_EXTRACTABLE_EXTENSIONS | DIRECT_READ_EXTENSIONS | CONVERTIBLE_EXTENSIONS
    ext_list = ",".join(f"'{e}'" for e in all_exts)

    total = conn.execute(text(f"""
        SELECT COUNT(*) FROM documents
        WHERE downloaded = 1 AND local_path IS NOT NULL
          AND LOWER(file_extension) IN ({ext_list})
    """)).scalar()

    extracted = conn.execute(text(f"""
        SELECT COUNT(DISTINCT dt.document_id) FROM document_text dt
        JOIN documents d ON d.id = dt.document_id
        WHERE dt.method IN ('pymupdf', 'direct_read')
          AND LOWER(d.file_extension) IN ({ext_list})
    """)).scalar()

    failed = conn.execute(text(f"""
        SELECT COUNT(DISTINCT pl.document_id) FROM processing_log pl
        JOIN documents d ON d.id = pl.document_id
        WHERE pl.operation = 'text_extract' AND pl.status = 'failed'
          AND LOWER(d.file_extension) IN ({ext_list})
          AND pl.document_id NOT IN (
              SELECT document_id FROM document_text WHERE method IN ('pymupdf', 'direct_read')
          )
    """)).scalar()

    total_pages = conn.execute(text("""
        SELECT COUNT(*) FROM document_text
        WHERE method IN ('pymupdf', 'direct_read')
    """)).scalar()

    return schemas.TextExtractionStatus(
        total_extractable=total,
        extracted=extracted,
        pending=total - extracted - failed,
        failed=failed,
        total_pages=total_pages,
    )


# ── Transcription status ──────────────────────────────────────────────────────

@router.get("/transcription-status", response_model=schemas.TranscriptionStatus)
def transcription_status(conn: Connection = Depends(get_db)):
    ext_list = ",".join(f"'{e}'" for e in TRANSCRIBABLE_EXTENSIONS)

    total = conn.execute(text(f"""
        SELECT COUNT(*) FROM documents
        WHERE downloaded = 1 AND local_path IS NOT NULL
          AND LOWER(file_extension) IN ({ext_list})
    """)).scalar()

    transcribed = conn.execute(text(f"""
        SELECT COUNT(DISTINCT dt.document_id) FROM document_text dt
        JOIN documents d ON d.id = dt.document_id
        WHERE dt.method = 'whisper'
          AND LOWER(d.file_extension) IN ({ext_list})
    """)).scalar()

    failed = conn.execute(text(f"""
        SELECT COUNT(DISTINCT pl.document_id) FROM processing_log pl
        JOIN documents d ON d.id = pl.document_id
        WHERE pl.operation = 'transcribe' AND pl.status = 'failed'
          AND LOWER(d.file_extension) IN ({ext_list})
          AND pl.document_id NOT IN (SELECT document_id FROM document_text WHERE method = 'whisper')
    """)).scalar()

    return schemas.TranscriptionStatus(
        total_transcribable=total,
        transcribed=transcribed,
        pending=total - transcribed - failed,
        failed=failed,
    )


# ── Preview endpoint (with LibreOffice conversion) ────────────────────────────

@router.get("/{doc_id}/preview")
def preview_document(doc_id: int, conn: Connection = Depends(get_db)):
    row = conn.execute(
        text("SELECT local_path, title, file_extension, downloaded, file_size_mb FROM documents WHERE id = :did"),
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

    # Office types — serve cached PDF or convert on demand
    if ext in CONVERTIBLE_EXTENSIONS:
        resolved = _resolve_doc_path(doc)
        cache_path = resolved.parent / (resolved.name + ".preview.pdf")

        # Serve from cache
        if cache_path.exists():
            return FileResponse(str(cache_path), media_type="application/pdf")

        # Size guard for on-demand conversion
        size_mb = doc.get("file_size_mb") or 0
        if size_mb > _MAX_ONDEMAND_MB:
            raise HTTPException(
                413,
                f"File too large for on-demand conversion ({size_mb:.1f} MB). "
                f"Run 'python convert_previews.py' to batch-convert."
            )

        try:
            ok = convert_to_pdf(resolved, cache_path)
        except FileNotFoundError:
            raise HTTPException(
                501,
                "LibreOffice not installed. Install it to preview Office documents."
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Conversion timed out")

        if not ok:
            raise HTTPException(500, "LibreOffice conversion failed")

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


# ── Transcription endpoints ──────────────────────────────────────────────────

@router.get("/{doc_id}/transcript", response_model=schemas.TranscriptionResult)
def get_transcript(doc_id: int, conn: Connection = Depends(get_db)):
    row = conn.execute(text(
        "SELECT document_id, text_content, segments_json, duration_seconds, "
        "processing_seconds, method, created_at "
        "FROM document_text WHERE document_id = :did AND method = 'whisper'"
    ), {"did": doc_id}).mappings().first()

    if not row:
        raise HTTPException(404, "No transcription found for this document")

    r = dict(row)
    segments = json.loads(r["segments_json"]) if r.get("segments_json") else []

    return schemas.TranscriptionResult(
        document_id=r["document_id"],
        text=r["text_content"],
        segments=[schemas.TranscriptionSegment(**s) for s in segments],
        duration_seconds=r.get("duration_seconds"),
        processing_seconds=r.get("processing_seconds"),
        method=r["method"],
        created_at=r.get("created_at"),
    )


@router.post("/{doc_id}/transcribe")
def transcribe_document_endpoint(doc_id: int, conn: Connection = Depends(get_db)):
    from app.services.transcription import is_civic_media_available, transcribe_document

    # Get document info
    row = conn.execute(text(
        "SELECT id, title, file_extension, local_path, downloaded FROM documents WHERE id = :did"
    ), {"did": doc_id}).mappings().first()

    if not row:
        raise HTTPException(404, "Document not found")

    doc = dict(row)
    ext = (doc.get("file_extension") or "").lower()

    if ext not in TRANSCRIBABLE_EXTENSIONS:
        raise HTTPException(400, f".{ext} files are not transcribable")

    if not doc["downloaded"] or not doc["local_path"]:
        raise HTTPException(404, "Document file not available (metadata only)")

    if not is_civic_media_available():
        raise HTTPException(503, "Transcription service (civic_media) is not running. Start it and try again.")

    result = transcribe_document(
        conn, doc["id"], doc["local_path"], ext, doc.get("title", ""))

    if not result["success"]:
        raise HTTPException(500, f"Transcription failed: {result['error']}")

    return {
        "success": True,
        "document_id": doc_id,
        "segment_count": result["segment_count"],
        "duration_seconds": result["duration"],
        "text_preview": result["text"][:200] + "..." if len(result["text"]) > 200 else result["text"],
    }


# ── Text extraction endpoints ───────────────────────────────────────────────

@router.get("/{doc_id}/extracted-text", response_model=schemas.ExtractedTextResult)
def get_extracted_text(doc_id: int, conn: Connection = Depends(get_db)):
    rows = conn.execute(text(
        "SELECT document_id, page_number, text_content, method, created_at "
        "FROM document_text WHERE document_id = :did AND method IN ('pymupdf', 'direct_read') "
        "ORDER BY page_number"
    ), {"did": doc_id}).mappings().all()

    if not rows:
        raise HTTPException(404, "No extracted text found for this document")

    pages = [schemas.ExtractedTextPage(
        page_number=r["page_number"],
        text=r["text_content"],
        method=r["method"],
    ) for r in rows]

    total_chars = sum(len(p.text) for p in pages)
    first = dict(rows[0])

    return schemas.ExtractedTextResult(
        document_id=doc_id,
        pages=pages,
        total_pages=len(pages),
        total_chars=total_chars,
        method=first["method"],
        created_at=first.get("created_at"),
    )


@router.post("/{doc_id}/extract-text")
def extract_text_endpoint(doc_id: int, conn: Connection = Depends(get_db)):
    from app.services.ocr import extract_text_from_document

    row = conn.execute(text(
        "SELECT id, title, file_extension, local_path, downloaded FROM documents WHERE id = :did"
    ), {"did": doc_id}).mappings().first()

    if not row:
        raise HTTPException(404, "Document not found")

    doc = dict(row)
    ext = (doc.get("file_extension") or "").lower()

    all_exts = TEXT_EXTRACTABLE_EXTENSIONS | DIRECT_READ_EXTENSIONS | CONVERTIBLE_EXTENSIONS
    if ext not in all_exts:
        raise HTTPException(400, f".{ext} files are not supported for text extraction")

    if not doc["downloaded"] or not doc["local_path"]:
        raise HTTPException(404, "Document file not available (metadata only)")

    result = extract_text_from_document(
        conn, doc["id"], doc["local_path"], ext, doc.get("title", ""))

    if not result["success"]:
        raise HTTPException(500, f"Text extraction failed: {result['error']}")

    return {
        "success": True,
        "document_id": doc_id,
        "page_count": result["page_count"],
        "char_count": result["char_count"],
    }


# ── Email (.msg) parsing endpoint ────────────────────────────────────────

@router.get("/{doc_id}/email", response_model=schemas.EmailMessage)
def get_email(doc_id: int, conn: Connection = Depends(get_db)):
    row = conn.execute(
        text("SELECT id, local_path, file_extension, downloaded FROM documents WHERE id = :did"),
        {"did": doc_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Document not found")

    doc = dict(row)
    ext = (doc.get("file_extension") or "").lower()
    if ext != "msg":
        raise HTTPException(400, f".{ext} is not an email file")

    resolved = _resolve_doc_path(doc)

    try:
        import extract_msg
        msg = extract_msg.Message(str(resolved))
        result = schemas.EmailMessage(
            document_id=doc_id,
            sender=msg.sender or "",
            to=msg.to or "",
            cc=msg.cc or "",
            subject=msg.subject or "",
            date=str(msg.date) if msg.date else "",
            body_html=msg.htmlBody.decode("utf-8", errors="replace") if isinstance(msg.htmlBody, bytes) else (msg.htmlBody or ""),
            body_text=msg.body or "",
        )
        msg.close()
        return result
    except ImportError:
        raise HTTPException(501, "extract-msg not installed. Run: pip install extract-msg>=0.48")
    except Exception as e:
        raise HTTPException(500, f"Failed to parse .msg file: {e}")
