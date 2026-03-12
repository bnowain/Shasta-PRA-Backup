#!/usr/bin/env python3
"""Batch text extraction from PDF, TXT/CSV, and Office documents.

Usage:
    python ocr_documents.py              # Extract text from all unprocessed docs
    python ocr_documents.py --dry-run    # Show what would be processed
    python ocr_documents.py --force      # Re-extract everything
    python ocr_documents.py --limit 10   # Only process first 10
    python ocr_documents.py --pdf-only   # Only process PDFs
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

# Project imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import (
    DB_PATH, BASE_DIR,
    TEXT_EXTRACTABLE_EXTENSIONS, DIRECT_READ_EXTENSIONS, CONVERTIBLE_EXTENSIONS,
    IMAGE_OCR_EXTENSIONS, SURYA_MIN_CHARS_PER_PAGE,
)


def get_documents(conn, force=False, limit=0, pdf_only=False):
    """Get documents to extract text from."""
    if pdf_only:
        exts = TEXT_EXTRACTABLE_EXTENSIONS
    else:
        exts = TEXT_EXTRACTABLE_EXTENSIONS | DIRECT_READ_EXTENSIONS | CONVERTIBLE_EXTENSIONS | IMAGE_OCR_EXTENSIONS

    ext_list = ",".join(f"'{e}'" for e in exts)

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

    cols = ["id", "title", "file_extension", "file_size_mb", "local_path", "request_pretty_id"]
    return [dict(zip(cols, row)) for row in conn.execute(sql).fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Batch extract text from documents")
    parser.add_argument("--force", action="store_true", help="Re-extract already processed files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    parser.add_argument("--limit", type=int, default=0, help="Max documents to process")
    parser.add_argument("--pdf-only", action="store_true", help="Only process PDF files")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    # Check PyMuPDF availability
    try:
        import fitz
        print(f"PyMuPDF version: {fitz.version[0]}")
    except ImportError:
        print("PyMuPDF not installed. Run: pip install PyMuPDF")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Ensure tables exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS document_text (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            page_number INTEGER NOT NULL DEFAULT 0,
            text_content TEXT NOT NULL,
            method TEXT NOT NULL,
            segments_json TEXT,
            duration_seconds REAL,
            processing_seconds REAL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (document_id) REFERENCES documents(id),
            UNIQUE(document_id, page_number, method)
        );
        CREATE TABLE IF NOT EXISTS processing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            operation TEXT NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (document_id) REFERENCES documents(id)
        );
    """)
    conn.commit()

    docs = get_documents(conn, force=args.force, limit=args.limit, pdf_only=args.pdf_only)

    if not docs:
        print("No documents to extract text from.")
        conn.close()
        return

    total_size = sum(d.get("file_size_mb") or 0 for d in docs)
    print(f"\n{len(docs)} documents to process ({total_size:.1f} MB total)")

    if args.dry_run:
        print()
        for i, doc in enumerate(docs):
            size = doc.get("file_size_mb") or 0
            print(f"  [{i+1}/{len(docs)}] {doc['title']} "
                  f"(.{doc['file_extension']}, {size:.1f} MB, req {doc['request_pretty_id']})")
        print(f"\nDry run complete. Use without --dry-run to extract text.")
        conn.close()
        return

    from app.services.ocr import extract_text_from_document

    print()
    ok_count = empty_count = fail_count = 0
    total_pages = total_chars = 0
    t_start = time.time()

    def safe_print(msg, **kwargs):
        """Print with fallback for non-encodable characters."""
        try:
            print(msg, **kwargs)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode("ascii"), **kwargs)

    for i, doc in enumerate(docs):
        size = doc.get("file_size_mb") or 0
        safe_print(f"[{i+1}/{len(docs)}] {doc['title']} "
                   f"(.{doc['file_extension']}, {size:.1f} MB)... ",
                   end="", flush=True)

        t0 = time.time()
        result = extract_text_from_document(
            conn, doc["id"], doc["local_path"],
            doc["file_extension"], doc.get("title", ""))
        elapsed = time.time() - t0

        if result["success"]:
            if result["char_count"] > 0:
                ok_count += 1
                total_pages += result["page_count"]
                total_chars += result["char_count"]
                print(f"OK ({result['page_count']} pages, {result['char_count']:,} chars, {elapsed:.1f}s)")
            else:
                empty_count += 1
                print(f"EMPTY ({result['page_count']} pages, no text, {elapsed:.1f}s)")
        else:
            fail_count += 1
            print(f"FAILED: {result['error']}")

    total_elapsed = time.time() - t_start
    print(f"\nDone: {ok_count} extracted, {empty_count} empty, {fail_count} failed "
          f"({total_pages:,} pages, {total_chars:,} chars, {total_elapsed:.1f}s)")
    conn.close()


if __name__ == "__main__":
    main()
