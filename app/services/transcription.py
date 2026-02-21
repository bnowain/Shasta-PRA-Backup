"""Transcription client — sends audio/video files to civic_media for Whisper transcription.

Works with both raw sqlite3 connections (batch script) and SQLAlchemy connections (API routes).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import requests

from app.config import (
    BASE_DIR,
    CIVIC_MEDIA_URL,
    TRANSCRIBE_ENDPOINT,
    TRANSCRIBABLE_EXTENSIONS,
    TRANSCRIBE_CONNECT_TIMEOUT,
    TRANSCRIBE_READ_TIMEOUT,
)

log = logging.getLogger(__name__)


# ── Connection helpers (sqlite3 vs sqlalchemy) ───────────────────────────────

def _execute(conn, sql, params=None):
    """Execute SQL on either a raw sqlite3 or sqlalchemy connection."""
    if hasattr(conn, "execute") and hasattr(conn, "cursor"):
        # raw sqlite3
        if params:
            return conn.execute(sql, params)
        return conn.execute(sql)
    else:
        # sqlalchemy Connection
        from sqlalchemy import text
        if params:
            # Convert ? placeholders to :named for sqlalchemy
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


# ── Core functions ───────────────────────────────────────────────────────────

def is_civic_media_available() -> bool:
    """Quick check if civic_media is running (3s timeout)."""
    try:
        resp = requests.get(
            f"{CIVIC_MEDIA_URL}/api/health",
            timeout=TRANSCRIBE_CONNECT_TIMEOUT,
        )
        return resp.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def transcribe_document(conn, doc_id: int, local_path: str, ext: str, title: str = "") -> dict:
    """Send a file to civic_media for transcription, store result in DB.

    Returns: {success: bool, text: str, segment_count: int, duration: float, error: str}
    """
    result = {"success": False, "text": "", "segment_count": 0, "duration": 0.0, "error": ""}

    # Log start
    now = datetime.now().isoformat()
    _execute(conn,
        "INSERT INTO processing_log (document_id, operation, status, started_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (doc_id, "transcribe", "processing", now, now))
    _commit(conn)

    file_path = Path(local_path)
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    if not file_path.exists():
        result["error"] = f"File not found: {file_path}"
        _execute(conn,
            "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("failed", result["error"], datetime.now().isoformat(), doc_id, "transcribe", "processing"))
        _commit(conn)
        return result

    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                TRANSCRIBE_ENDPOINT,
                files={"file": (file_path.name, f)},
                timeout=(TRANSCRIBE_CONNECT_TIMEOUT, TRANSCRIBE_READ_TIMEOUT),
            )

        if resp.status_code != 200:
            result["error"] = f"civic_media returned {resp.status_code}: {resp.text[:200]}"
            _execute(conn,
                "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                "WHERE document_id=? AND operation=? AND status=?",
                ("failed", result["error"], datetime.now().isoformat(), doc_id, "transcribe", "processing"))
            _commit(conn)
            return result

        data = resp.json()
        text_content = data.get("text", "")
        segments = data.get("segments", [])
        duration = data.get("duration_seconds", 0.0)
        processing = data.get("processing_seconds", 0.0)

        # Store in document_text
        _execute(conn,
            "INSERT OR REPLACE INTO document_text "
            "(document_id, page_number, text_content, method, segments_json, duration_seconds, processing_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc_id, 0, text_content, "whisper", json.dumps(segments), duration, processing))

        # Update processing_log
        _execute(conn,
            "UPDATE processing_log SET status=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("completed", datetime.now().isoformat(), doc_id, "transcribe", "processing"))
        _commit(conn)

        result["success"] = True
        result["text"] = text_content
        result["segment_count"] = len(segments)
        result["duration"] = duration
        return result

    except requests.ConnectionError:
        result["error"] = "civic_media is not running"
    except requests.Timeout:
        result["error"] = "Transcription timed out (file may be too large)"
    except Exception as e:
        result["error"] = str(e)

    _execute(conn,
        "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
        "WHERE document_id=? AND operation=? AND status=?",
        ("failed", result["error"], datetime.now().isoformat(), doc_id, "transcribe", "processing"))
    _commit(conn)
    return result


def get_untranscribed_documents(conn, limit: int = 0) -> list[dict]:
    """Query docs with transcribable extensions not yet in document_text."""
    ext_list = ",".join(f"'{e}'" for e in TRANSCRIBABLE_EXTENSIONS)
    sql = f"""
        SELECT d.id, d.title, d.file_extension, d.file_size_mb, d.local_path,
               d.request_pretty_id
        FROM documents d
        WHERE d.downloaded = 1
          AND d.local_path IS NOT NULL
          AND LOWER(d.file_extension) IN ({ext_list})
          AND d.id NOT IN (
              SELECT document_id FROM document_text WHERE method = 'whisper'
          )
        ORDER BY d.file_size_mb ASC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"

    result = _execute(conn, sql)
    return _fetchall(result)
