#!/usr/bin/env python3
"""Ingest new and updated PRA records from Shasta County NextRequest.

Runs all scrape phases: departments, listings, details, document downloads,
PDF conversion, Whisper transcription, and text extraction.

Usage:
    python ingest.py              # Full ingest (new + updated + post-processing)
    python ingest.py --no-docs    # Skip document downloads and post-processing
    python ingest.py --meta-only  # Listings + details only (same as --no-docs)
"""

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

# ── Bootstrap path so app.* imports work ─────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scraper.py").replace("scraper.py", ""))


def log(phase, msg):
    print(f"[{phase.upper():>16}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Ingest new/updated PRA records.")
    parser.add_argument("--no-docs", "--meta-only", action="store_true",
                        help="Skip document downloads and post-processing")
    args = parser.parse_args()

    from scraper import API, Scraper, init_db, RAW_DIR, OUTPUT_DIR, DOCS_DIR, DELAY_API, DELAY_DOWNLOAD
    from app.config import DB_PATH, CONVERTIBLE_EXTENSIONS, SOFFICE_PATH

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    conn = init_db(DB_PATH)
    api = API()

    log("init", "Initializing session...")
    api.init_session()
    time.sleep(1)

    scraper = Scraper(conn, api)

    # ── Phase 1: Departments ──────────────────────────────────────────────────
    log("departments", "Refreshing departments...")
    before_dept = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
    scraper.phase1_departments()
    after_dept = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
    new_dept = after_dept - before_dept
    log("departments", f"{after_dept} total ({'+' + str(new_dept) + ' new' if new_dept else 'no change'})")

    # ── Phase 2: Listings ─────────────────────────────────────────────────────
    state_before = dict(conn.execute(
        "SELECT pretty_id, request_state FROM requests"
    ).fetchall())

    log("listings", "Scanning request listings...")
    before_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    scraper.phase2_listings()
    after_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    new_count = after_req - before_req

    state_after = dict(conn.execute(
        "SELECT pretty_id, request_state FROM requests"
    ).fetchall())
    changed_ids = {pid for pid, st in state_after.items()
                   if pid in state_before and state_before[pid] != st}

    log("listings", f"Found {new_count} new requests ({after_req} total)")

    # ── Phase 3: Details ──────────────────────────────────────────────────────
    incomplete_ids = {r[0] for r in conn.execute("""
        SELECT r.pretty_id FROM requests r
        WHERE r.detail_scraped = 1 AND (
            r.raw_detail_json IS NULL
            OR r.request_text IS NULL OR r.request_text = ''
            OR r.departments_json IS NULL
            OR r.pretty_id NOT IN (
                SELECT DISTINCT request_pretty_id FROM timeline_events
            )
        )
    """).fetchall()}

    TERMINAL = ('closed', 'completed')
    new_ids = {r[0] for r in conn.execute(
        "SELECT pretty_id FROM requests WHERE detail_scraped=0"
    ).fetchall()}
    new_set = new_ids | incomplete_ids

    active_ids = {r[0] for r in conn.execute(
        "SELECT pretty_id FROM requests WHERE detail_scraped=1"
    ).fetchall()}
    refresh_set = {pid for pid in active_ids
                   if state_after.get(pid, '').lower() not in TERMINAL}
    refresh_set |= changed_ids

    all_ids = sorted(new_set | refresh_set)
    total = len(all_ids)
    n_new = len(new_set)
    n_refresh = len(refresh_set - new_set)

    if total == 0:
        log("details", "All requests up to date")
    else:
        label_parts = []
        if n_new:
            label_parts.append(f"{n_new} new")
        if n_refresh:
            label_parts.append(f"{n_refresh} to refresh")
        log("details", f"Scraping details ({', '.join(label_parts)})...")

        for i, pretty_id in enumerate(all_ids):
            tag = "new" if pretty_id in new_set else "refresh"
            log("details", f"[{tag}] {pretty_id} ({i + 1}/{total})")
            try:
                scraper._scrape_one(pretty_id)
                conn.execute(
                    "UPDATE requests SET detail_scraped=1 WHERE pretty_id=?",
                    (pretty_id,))
            except Exception as e:
                log("details", f"ERROR {pretty_id}: {e}")
                conn.execute(
                    "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                    ("error", f"{pretty_id}: {e}"))
            time.sleep(DELAY_API)
            if (i + 1) % 50 == 0:
                conn.commit()
        conn.commit()
        log("details", f"Done: {n_new} new, {n_refresh} refreshed")

    if args.no_docs:
        log("done", "Skipping document phases (--no-docs)")
        conn.close()
        return

    # ── Phase 4: Download documents ───────────────────────────────────────────
    pending = conn.execute("""
        SELECT id, request_pretty_id, title, asset_url
        FROM documents WHERE downloaded=0
        ORDER BY request_pretty_id
    """).fetchall()
    doc_total = len(pending)

    if doc_total == 0:
        log("downloads", "No documents to download")
    else:
        log("downloads", f"Downloading {doc_total} documents...")
        dl_ok = dl_fail = 0

        for j, (doc_id, pretty_id, title, asset_url) in enumerate(pending):
            log("downloads", f"{title or f'doc {doc_id}'} ({j + 1}/{doc_total})")

            signed_url = api.get_download_redirect(doc_id)
            if not signed_url and asset_url:
                signed_url = ("https:" + asset_url
                              if asset_url.startswith("//") else asset_url)
            if not signed_url:
                dl_fail += 1
                conn.execute(
                    "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                    ("no_url", f"doc {doc_id} ({title}) for {pretty_id}"))
                continue

            try:
                req_dir = DOCS_DIR / pretty_id
                req_dir.mkdir(parents=True, exist_ok=True)

                safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title or f'doc_{doc_id}')
                if not safe.strip():
                    safe = f"document_{doc_id}"
                path = req_dir / safe

                if path.exists():
                    stem, ext = path.stem, path.suffix
                    c = 1
                    while path.exists():
                        path = req_dir / f"{stem}_{c}{ext}"
                        c += 1

                success, sha_or_err, size = api.download_file(signed_url, path)
                if success:
                    size_mb = round(size / (1024 * 1024), 2)
                    conn.execute("""
                        UPDATE documents
                        SET downloaded=1, local_path=?, sha256=?, file_size_bytes=?, file_size_mb=?
                        WHERE id=?
                    """, (str(path), sha_or_err, size, size_mb, doc_id))
                    dl_ok += 1
                else:
                    dl_fail += 1
                    conn.execute(
                        "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                        ("download_fail", f"doc {doc_id} ({title}): {sha_or_err}"))
            except Exception as e:
                dl_fail += 1
                conn.execute(
                    "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                    ("download_error", f"doc {doc_id}: {e}"))

            time.sleep(DELAY_DOWNLOAD)
            if (j + 1) % 50 == 0:
                conn.commit()

        conn.commit()
        parts = [f"{dl_ok} downloaded"]
        if dl_fail:
            parts.append(f"{dl_fail} failed")
        log("downloads", ", ".join(parts))

    # ── Phase 5: Convert document previews ────────────────────────────────────
    from app.routers.documents import convert_to_pdf

    convertible = conn.execute(f"""
        SELECT id, title, file_extension, local_path
        FROM documents
        WHERE downloaded = 1
          AND local_path IS NOT NULL
          AND LOWER(file_extension) IN ({','.join(f"'{e}'" for e in CONVERTIBLE_EXTENSIONS)})
        ORDER BY id
    """).fetchall()

    to_convert = []
    for row in convertible:
        doc_id, title, ext, local_path = row
        fp = Path(local_path)
        if not fp.is_absolute():
            fp = ROOT / fp
        cache = fp.parent / (fp.name + ".preview.pdf")
        if fp.exists() and not cache.exists():
            to_convert.append((doc_id, title, fp, cache))

    if not to_convert:
        log("converting", "No documents need PDF conversion")
    else:
        log("converting", f"Converting {len(to_convert)} documents to PDF...")
        cv_ok = cv_fail = 0
        for k, (doc_id, title, fp, cache) in enumerate(to_convert):
            log("converting", f"{title or f'doc {doc_id}'} ({k + 1}/{len(to_convert)})")
            try:
                if convert_to_pdf(fp, cache, timeout=180):
                    cv_ok += 1
                else:
                    cv_fail += 1
            except Exception as e:
                log("converting", f"ERROR: {e}")
                cv_fail += 1
        parts_cv = [f"{cv_ok} converted"]
        if cv_fail:
            parts_cv.append(f"{cv_fail} failed")
        log("converting", ", ".join(parts_cv))

    # ── Phase 6: Transcribe audio/video ───────────────────────────────────────
    from app.services.transcription import (is_civic_media_available,
                                             transcribe_document,
                                             get_untranscribed_documents)

    if not is_civic_media_available():
        log("transcribing", "Skipping — civic_media not running")
    else:
        untranscribed = get_untranscribed_documents(conn)
        tr_total = len(untranscribed)
        if tr_total == 0:
            log("transcribing", "No audio/video files to transcribe")
        else:
            log("transcribing", f"Transcribing {tr_total} files...")
            tr_ok = tr_fail = 0
            for k, doc in enumerate(untranscribed):
                doc_label = doc['title'] or f"doc {doc['id']}"
                log("transcribing", f"{doc_label} ({k + 1}/{tr_total})")
                result = transcribe_document(
                    conn, doc["id"], doc["local_path"],
                    doc["file_extension"], doc.get("title", ""))
                if result["success"]:
                    tr_ok += 1
                else:
                    tr_fail += 1
            parts_tr = [f"{tr_ok} transcribed"]
            if tr_fail:
                parts_tr.append(f"{tr_fail} failed")
            log("transcribing", ", ".join(parts_tr))

    # ── Phase 7: Extract text from documents ──────────────────────────────────
    from app.services.ocr import extract_text_from_document, get_unprocessed_documents

    unprocessed = get_unprocessed_documents(conn)
    te_total = len(unprocessed)
    if te_total == 0:
        log("text_extract", "No documents need text extraction")
    else:
        log("text_extract", f"Extracting text from {te_total} documents...")
        te_ok = te_empty = te_fail = 0
        for k, doc in enumerate(unprocessed):
            te_label = doc['title'] or f"doc {doc['id']}"
            log("text_extract", f"{te_label} ({k + 1}/{te_total})")
            result = extract_text_from_document(
                conn, doc["id"], doc["local_path"],
                doc["file_extension"], doc.get("title", ""))
            if result["success"]:
                if result["char_count"] > 0:
                    te_ok += 1
                else:
                    te_empty += 1
            else:
                te_fail += 1
        parts_te = [f"{te_ok} extracted"]
        if te_empty:
            parts_te.append(f"{te_empty} empty")
        if te_fail:
            parts_te.append(f"{te_fail} failed")
        log("text_extract", ", ".join(parts_te))

    # ── Summary ───────────────────────────────────────────────────────────────
    final_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    final_new = final_req - before_req
    summary_parts = []
    if final_new:
        summary_parts.append(f"{final_new} new requests")
    if n_refresh:
        summary_parts.append(f"{n_refresh} refreshed")
    if doc_total:
        summary_parts.append(f"{doc_total} documents processed")
    summary = ", ".join(summary_parts) if summary_parts else "everything up to date"

    conn.execute(
        "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
        ("ingest_complete", summary))
    conn.commit()
    conn.close()

    log("done", f"Complete: {summary} ({final_req} total requests)")


if __name__ == "__main__":
    main()
