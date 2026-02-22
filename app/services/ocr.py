"""Text extraction service — extracts native text from PDFs and reads text files.

Works with both raw sqlite3 connections (batch script) and SQLAlchemy connections (API routes).
Phase 1: PyMuPDF for native PDF text + direct read for TXT/CSV.
Phase 2 (future): EasyOCR for scanned pages and images.
"""

import logging
from datetime import datetime
from pathlib import Path

from app.config import (
    BASE_DIR,
    TEXT_EXTRACTABLE_EXTENSIONS,
    DIRECT_READ_EXTENSIONS,
    CONVERTIBLE_EXTENSIONS,
    OCR_MAX_FILE_SIZE_MB,
)

log = logging.getLogger(__name__)


# ── Connection helpers (sqlite3 vs sqlalchemy) ───────────────────────────────

def _execute(conn, sql, params=None):
    """Execute SQL on either a raw sqlite3 or sqlalchemy connection."""
    if hasattr(conn, "execute") and hasattr(conn, "cursor"):
        if params:
            return conn.execute(sql, params)
        return conn.execute(sql)
    else:
        from sqlalchemy import text
        if params:
            named_sql = sql
            named_params = {}
            for i, val in enumerate(params):
                key = f"p{i}"
                named_sql = named_sql.replace("?", f":{key}", 1)
                named_params[key] = val
            return conn.execute(text(named_sql), named_params)
        return conn.execute(text(sql))


def _commit(conn):
    """Commit on either connection type."""
    if hasattr(conn, "cursor"):
        conn.commit()
    else:
        conn.commit()


def _fetchall(result):
    """Fetch all rows as dicts from either connection type."""
    if hasattr(result, "mappings"):
        return [dict(r) for r in result.mappings().all()]
    else:
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row)) for row in result.fetchall()]


def _fetchone(result):
    """Fetch one row as dict from either connection type."""
    if hasattr(result, "mappings"):
        row = result.mappings().first()
        return dict(row) if row else None
    else:
        row = result.fetchone()
        if not row:
            return None
        cols = [d[0] for d in result.description]
        return dict(zip(cols, row))


# ── Core extraction functions ────────────────────────────────────────────────

def extract_text_from_pdf(file_path: Path) -> list[dict]:
    """Extract text from each page of a PDF using PyMuPDF.

    Returns: list of {page_number: int, text: str}
    """
    import fitz  # PyMuPDF

    pages = []
    with fitz.open(str(file_path)) as doc:
        for i, page in enumerate(doc):
            text = page.get_text()
            pages.append({"page_number": i, "text": text.strip() if text else ""})
    return pages


def read_text_file(file_path: Path) -> str:
    """Read a text file, trying UTF-8 first then latin-1 fallback."""
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1")


def extract_text_from_document(conn, doc_id: int, local_path: str, ext: str, title: str = "") -> dict:
    """Extract text from a document and store in document_text.

    Handles PDFs (PyMuPDF), TXT/CSV (direct read), and Office docs (via .preview.pdf).

    Returns: {success: bool, page_count: int, char_count: int, error: str}
    """
    result = {"success": False, "page_count": 0, "char_count": 0, "error": ""}

    # Log start
    now = datetime.now().isoformat()
    _execute(conn,
        "INSERT INTO processing_log (document_id, operation, status, started_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (doc_id, "text_extract", "processing", now, now))
    _commit(conn)

    file_path = Path(local_path)
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    if not file_path.exists():
        result["error"] = f"File not found: {file_path}"
        _execute(conn,
            "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
        _commit(conn)
        return result

    # Size guard
    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > OCR_MAX_FILE_SIZE_MB:
        result["error"] = f"File too large ({size_mb:.1f} MB > {OCR_MAX_FILE_SIZE_MB} MB limit)"
        _execute(conn,
            "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
        _commit(conn)
        return result

    ext_lower = ext.lower()

    try:
        pages = []
        method = ""

        if ext_lower in TEXT_EXTRACTABLE_EXTENSIONS:
            # PDF — extract per-page via PyMuPDF
            method = "pymupdf"
            pages = extract_text_from_pdf(file_path)

        elif ext_lower in DIRECT_READ_EXTENSIONS:
            # TXT/CSV — read entire file as one page
            method = "direct_read"
            text_content = read_text_file(file_path)
            pages = [{"page_number": 0, "text": text_content}]

        elif ext_lower in CONVERTIBLE_EXTENSIONS:
            # Office docs — extract from .preview.pdf if it exists
            preview_path = file_path.parent / (file_path.name + ".preview.pdf")
            if preview_path.exists():
                method = "pymupdf"
                pages = extract_text_from_pdf(preview_path)
            else:
                result["error"] = f"No preview PDF found for Office document (run convert_previews.py first)"
                _execute(conn,
                    "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                    "WHERE document_id=? AND operation=? AND status=?",
                    ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
                _commit(conn)
                return result
        else:
            result["error"] = f"Unsupported extension: .{ext_lower}"
            _execute(conn,
                "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                "WHERE document_id=? AND operation=? AND status=?",
                ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
            _commit(conn)
            return result

        # Store extracted text (per page)
        total_chars = 0
        pages_with_text = 0
        for page in pages:
            text = page["text"]
            total_chars += len(text)
            if text:
                pages_with_text += 1
            _execute(conn,
                "INSERT OR REPLACE INTO document_text "
                "(document_id, page_number, text_content, method) "
                "VALUES (?, ?, ?, ?)",
                (doc_id, page["page_number"], text, method))

        _commit(conn)

        # Update processing_log
        _execute(conn,
            "UPDATE processing_log SET status=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("completed", datetime.now().isoformat(), doc_id, "text_extract", "processing"))
        _commit(conn)

        result["success"] = True
        result["page_count"] = len(pages)
        result["char_count"] = total_chars
        return result

    except Exception as e:
        result["error"] = str(e)
        _execute(conn,
            "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
        _commit(conn)
        return result


def get_unprocessed_documents(conn, force: bool = False, limit: int = 0) -> list[dict]:
    """Get documents that haven't had text extracted yet.

    Includes PDFs, TXT/CSV, and Office docs with .preview.pdf files.
    """
    all_exts = TEXT_EXTRACTABLE_EXTENSIONS | DIRECT_READ_EXTENSIONS | CONVERTIBLE_EXTENSIONS
    ext_list = ",".join(f"'{e}'" for e in all_exts)

    if force:
        sql = f"""
            SELECT d.id, d.title, d.file_extension, d.file_size_mb, d.local_path,
                   d.request_pretty_id
            FROM documents d
            WHERE d.downloaded = 1
              AND d.local_path IS NOT NULL
              AND LOWER(d.file_extension) IN ({ext_list})
            ORDER BY d.file_size_mb ASC
        """
    else:
        sql = f"""
            SELECT d.id, d.title, d.file_extension, d.file_size_mb, d.local_path,
                   d.request_pretty_id
            FROM documents d
            WHERE d.downloaded = 1
              AND d.local_path IS NOT NULL
              AND LOWER(d.file_extension) IN ({ext_list})
              AND d.id NOT IN (
                  SELECT DISTINCT document_id FROM document_text
                  WHERE method IN ('pymupdf', 'direct_read')
              )
            ORDER BY d.file_size_mb ASC
        """

    if limit > 0:
        sql += f" LIMIT {limit}"

    result = _execute(conn, sql)
    return _fetchall(result)
