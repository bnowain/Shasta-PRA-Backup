"""Document file serving with path traversal protection."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.config import BASE_DIR, DOCS_DIR
from app.database import get_db

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("/{doc_id}/file")
def serve_document(doc_id: int, conn: Connection = Depends(get_db)):
    row = conn.execute(
        text("SELECT local_path, title, file_extension, downloaded FROM documents WHERE id = :did"),
        {"did": doc_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Document not found")

    doc = dict(row)
    if not doc["downloaded"] or not doc["local_path"]:
        raise HTTPException(404, "Document file not available (metadata only)")

    file_path = Path(doc["local_path"])
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    # Path traversal protection
    try:
        resolved = file_path.resolve()
        docs_resolved = DOCS_DIR.resolve()
        if not str(resolved).startswith(str(docs_resolved)):
            raise HTTPException(403, "Access denied")
    except (OSError, ValueError):
        raise HTTPException(400, "Invalid file path")

    if not resolved.exists():
        raise HTTPException(404, "File not found on disk")

    # Determine media type
    ext = (doc.get("file_extension") or "").lower()
    media_types = {
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
    media_type = media_types.get(ext, "application/octet-stream")

    # Viewable types: serve inline so iframes/embeds work
    inline_types = {"pdf", "jpg", "jpeg", "png", "gif", "webp", "bmp",
                    "mp4", "webm", "mp3", "m4a", "wav", "ogg", "txt", "csv"}
    if ext in inline_types:
        return FileResponse(str(resolved), media_type=media_type)

    # Everything else: serve as download with filename
    filename = doc.get("title") or f"document_{doc_id}"
    if ext and not filename.endswith(f".{ext}"):
        filename = f"{filename}.{ext}"
    return FileResponse(str(resolved), media_type=media_type, filename=filename)
