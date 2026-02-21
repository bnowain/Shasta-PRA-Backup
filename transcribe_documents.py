#!/usr/bin/env python3
"""Batch transcription of audio/video documents via civic_media Whisper endpoint.

Usage:
    python transcribe_documents.py              # Transcribe all untranscribed
    python transcribe_documents.py --dry-run    # Show what would be transcribed
    python transcribe_documents.py --force      # Re-transcribe everything
    python transcribe_documents.py --limit 5    # Only process first 5
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

# Project imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import DB_PATH, TRANSCRIBABLE_EXTENSIONS, BASE_DIR


def get_documents(conn, force=False, limit=0):
    """Get audio/video documents to transcribe."""
    ext_list = ",".join(f"'{e}'" for e in TRANSCRIBABLE_EXTENSIONS)

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
                  SELECT document_id FROM document_text WHERE method = 'whisper'
              )
            ORDER BY d.file_size_mb ASC
        """

    if limit > 0:
        sql += f" LIMIT {limit}"

    cols = ["id", "title", "file_extension", "file_size_mb", "local_path", "request_pretty_id"]
    return [dict(zip(cols, row)) for row in conn.execute(sql).fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Batch transcribe audio/video documents")
    parser.add_argument("--force", action="store_true", help="Re-transcribe already transcribed files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    parser.add_argument("--limit", type=int, default=0, help="Max documents to process")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    # Check civic_media availability
    from app.services.transcription import is_civic_media_available, transcribe_document

    if not args.dry_run:
        print("Checking civic_media availability... ", end="", flush=True)
        if not is_civic_media_available():
            print("NOT RUNNING")
            print("\ncivic_media must be running for transcription.")
            print("Start it with: cd civic_media && uvicorn app.main:app --reload")
            sys.exit(1)
        print("OK")

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

    docs = get_documents(conn, force=args.force, limit=args.limit)

    if not docs:
        print("No audio/video documents to transcribe.")
        conn.close()
        return

    total_size = sum(d.get("file_size_mb") or 0 for d in docs)
    print(f"\n{len(docs)} documents to transcribe ({total_size:.1f} MB total)")

    if args.dry_run:
        print()
        for i, doc in enumerate(docs):
            size = doc.get("file_size_mb") or 0
            print(f"  [{i+1}/{len(docs)}] {doc['title']} "
                  f"(.{doc['file_extension']}, {size:.1f} MB, req {doc['request_pretty_id']})")
        print(f"\nDry run complete. Use without --dry-run to transcribe.")
        conn.close()
        return

    print()
    ok_count = fail_count = 0
    t_start = time.time()

    for i, doc in enumerate(docs):
        size = doc.get("file_size_mb") or 0
        print(f"[{i+1}/{len(docs)}] {doc['title']} "
              f"(.{doc['file_extension']}, {size:.1f} MB, req {doc['request_pretty_id']})... ",
              end="", flush=True)

        t0 = time.time()
        result = transcribe_document(
            conn, doc["id"], doc["local_path"],
            doc["file_extension"], doc.get("title", ""))

        elapsed = time.time() - t0

        if result["success"]:
            ok_count += 1
            print(f"OK ({result['segment_count']} segments, "
                  f"{result['duration']:.0f}s audio, {elapsed:.1f}s wall)")
        else:
            fail_count += 1
            print(f"FAILED: {result['error']}")

    total_elapsed = time.time() - t_start
    print(f"\nDone: {ok_count} transcribed, {fail_count} failed ({total_elapsed:.1f}s total)")
    conn.close()


if __name__ == "__main__":
    main()
