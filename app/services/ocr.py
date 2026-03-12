"""Text extraction service — native text via PyMuPDF, scanned/image OCR via Surya.

Processing strategy per document type:
  PDF with native text  → PyMuPDF (fast, exact)
  Scanned/image PDF     → PyMuPDF per page, Surya fallback for pages below char threshold
  Office docs           → Extract from .preview.pdf via same PDF path
  TXT / CSV             → Direct read
  Images (jpg/png/tif)  → Surya directly

Surya runs as a subprocess via civic_media's Python venv (GPU PyTorch, RTX 5090).
This avoids Python 3.13/3.11 ABI incompatibility with compiled packages (numpy, torch).
See civic_media/SURYA_INSTALL.md and VISION_PIPELINE.md.
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from app.config import (
    BASE_DIR,
    CIVIC_MEDIA_PYTHON,
    CONVERTIBLE_EXTENSIONS,
    DIRECT_READ_EXTENSIONS,
    IMAGE_OCR_EXTENSIONS,
    OCR_MAX_FILE_SIZE_MB,
    SURYA_MIN_CHARS_PER_PAGE,
    SURYA_WORKER,
    TEXT_EXTRACTABLE_EXTENSIONS,
)

log = logging.getLogger(__name__)


def is_surya_available() -> bool:
    """Return True if civic_media's python and the surya worker script exist."""
    return (CIVIC_MEDIA_PYTHON is not None
            and Path(CIVIC_MEDIA_PYTHON).exists()
            and Path(SURYA_WORKER).exists())


# ── Connection helpers (sqlite3 vs sqlalchemy) ───────────────────────────────

def _execute(conn, sql, params=None):
    if hasattr(conn, "execute") and hasattr(conn, "cursor"):
        return conn.execute(sql, params) if params else conn.execute(sql)
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
    conn.commit()


def _fetchall(result):
    if hasattr(result, "mappings"):
        return [dict(r) for r in result.mappings().all()]
    cols = [d[0] for d in result.description]
    return [dict(zip(cols, row)) for row in result.fetchall()]


def _fetchone(result):
    if hasattr(result, "mappings"):
        row = result.mappings().first()
        return dict(row) if row else None
    row = result.fetchone()
    if not row:
        return None
    cols = [d[0] for d in result.description]
    return dict(zip(cols, row))


# ── Core extraction ───────────────────────────────────────────────────────────

def _surya_ocr(image_specs: list) -> list[str]:
    """Run Surya on a batch of image specs via civic_media's python subprocess.

    image_specs: list of dicts — either {"path": "..."} or {"pdf_path": "...", "page": N}
    Returns: list of text strings, one per spec.
    """
    payload = json.dumps({"images": image_specs})
    proc = subprocess.run(
        [CIVIC_MEDIA_PYTHON, SURYA_WORKER],
        input=payload,
        capture_output=True,
        text=True,
        timeout=300,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"surya_worker exited {proc.returncode}: {proc.stderr[:500]}")
    response = json.loads(proc.stdout)
    if response.get("error"):
        raise RuntimeError(f"surya_worker error: {response['error']}")
    return response["results"]


def extract_text_from_pdf(file_path: Path) -> list[dict]:
    """Extract text from each page of a PDF.

    Uses PyMuPDF for native text. For pages below SURYA_MIN_CHARS_PER_PAGE,
    falls back to Surya OCR if available.

    Returns: list of {page_number, text, method}
    """
    import fitz

    pages = []
    with fitz.open(str(file_path)) as doc:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            pages.append({"page_number": i, "text": text, "method": "pymupdf"})

    if not is_surya_available():
        return pages

    # Find pages that likely need OCR
    scanned = [p["page_number"] for p in pages if len(p["text"]) < SURYA_MIN_CHARS_PER_PAGE]
    if not scanned:
        return pages

    log.info(f"{file_path.name}: {len(scanned)} scanned page(s) → Surya")
    try:
        specs = [{"pdf_path": str(file_path), "page": idx} for idx in scanned]
        texts = _surya_ocr(specs)
        for page_idx, text in zip(scanned, texts):
            pages[page_idx]["text"] = text
            pages[page_idx]["method"] = "surya"
    except Exception as e:
        log.warning(f"Surya fallback failed for {file_path.name}: {e}")

    return pages


def extract_text_from_image(file_path: Path) -> str:
    """Run Surya OCR on a standalone image file (jpg, png, tif, etc.)."""
    texts = _surya_ocr([{"path": str(file_path)}])
    return texts[0] if texts else ""


def read_text_file(file_path: Path) -> str:
    """Read a text file, trying UTF-8 first then latin-1 fallback."""
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1")


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_text_from_document(conn, doc_id: int, local_path: str, ext: str, title: str = "") -> dict:
    """Extract text from a document and store results in document_text.

    Returns: {success, page_count, char_count, error}
    """
    result = {"success": False, "page_count": 0, "char_count": 0, "error": ""}

    now = datetime.now().isoformat()
    _execute(conn,
        "INSERT INTO processing_log (document_id, operation, status, started_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (doc_id, "text_extract", "processing", now, now))
    _commit(conn)

    file_path = Path(local_path.replace("\\", "/"))
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

    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > OCR_MAX_FILE_SIZE_MB:
        result["error"] = f"File too large ({size_mb:.1f} MB > {OCR_MAX_FILE_SIZE_MB} MB limit)"
        _execute(conn,
            "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
        _commit(conn)
        return result

    ext_lower = ext.lower().lstrip(".")

    try:
        pages = []

        if ext_lower in TEXT_EXTRACTABLE_EXTENSIONS:
            pages = extract_text_from_pdf(file_path)

        elif ext_lower in DIRECT_READ_EXTENSIONS:
            text = read_text_file(file_path)
            pages = [{"page_number": 0, "text": text, "method": "direct_read"}]

        elif ext_lower in CONVERTIBLE_EXTENSIONS:
            preview = file_path.parent / (file_path.name + ".preview.pdf")
            if not preview.exists():
                result["error"] = "No preview PDF found (run convert_previews.py first)"
                _execute(conn,
                    "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                    "WHERE document_id=? AND operation=? AND status=?",
                    ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
                _commit(conn)
                return result
            pages = extract_text_from_pdf(preview)

        elif ext_lower in IMAGE_OCR_EXTENSIONS:
            if not is_surya_available():
                result["error"] = "Surya not available (civic_media venv not found)"
                _execute(conn,
                    "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                    "WHERE document_id=? AND operation=? AND status=?",
                    ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
                _commit(conn)
                return result
            text = extract_text_from_image(file_path)
            pages = [{"page_number": 0, "text": text, "method": "surya"}]

        else:
            result["error"] = f"Unsupported extension: .{ext_lower}"
            _execute(conn,
                "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                "WHERE document_id=? AND operation=? AND status=?",
                ("failed", result["error"], datetime.now().isoformat(), doc_id, "text_extract", "processing"))
            _commit(conn)
            return result

        # Store per-page results
        total_chars = 0
        for page in pages:
            text = page["text"]
            total_chars += len(text)
            _execute(conn,
                "INSERT OR REPLACE INTO document_text "
                "(document_id, page_number, text_content, method) VALUES (?, ?, ?, ?)",
                (doc_id, page["page_number"], text, page["method"]))

        _commit(conn)

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
    """Get documents that need text extraction.

    Excludes:
    - Docs with any surya result
    - Docs with direct_read result
    - Docs with pymupdf result that has meaningful content (>= SURYA_MIN_CHARS_PER_PAGE total)

    Re-includes docs that only have empty pymupdf rows (scanned PDFs awaiting Surya).
    """
    all_exts = (TEXT_EXTRACTABLE_EXTENSIONS | DIRECT_READ_EXTENSIONS
                | CONVERTIBLE_EXTENSIONS | IMAGE_OCR_EXTENSIONS)
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
                  SELECT document_id FROM document_text
                  WHERE method IN ('surya', 'direct_read')
                  UNION
                  SELECT document_id FROM document_text
                  WHERE method = 'pymupdf'
                  GROUP BY document_id
                  HAVING SUM(LENGTH(text_content)) >= {SURYA_MIN_CHARS_PER_PAGE}
              )
            ORDER BY d.file_size_mb ASC
        """

    if limit > 0:
        sql += f" LIMIT {limit}"

    result = _execute(conn, sql)
    return _fetchall(result)
