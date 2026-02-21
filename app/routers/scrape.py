"""SSE endpoint for live scraping with progress."""

import asyncio
import json
import queue
import sqlite3
import threading
import time

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from app.config import DB_PATH

router = APIRouter(prefix="/api/scrape", tags=["scrape"])

_lock = threading.Lock()


def _send(q, phase, message, progress, **extra):
    q.put({"phase": phase, "message": message, "progress": progress, **extra})


def _worker(q):
    try:
        import re
        from scraper import (API, Scraper, init_db, RAW_DIR, OUTPUT_DIR,
                             DOCS_DIR, DELAY_API, DELAY_DOWNLOAD)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        DOCS_DIR.mkdir(parents=True, exist_ok=True)

        conn = init_db(DB_PATH)
        api = API()

        _send(q, "init", "Initializing session...", 0)
        api.init_session()
        time.sleep(1)

        scraper = Scraper(conn, api)

        # ── Phase 1: Departments ─────────────────────────────────────
        _send(q, "departments", "Refreshing departments...", 5)
        before_dept = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
        scraper.phase1_departments()
        after_dept = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
        new_dept = after_dept - before_dept
        _send(q, "departments", f"{after_dept} departments ({'+' + str(new_dept) if new_dept else 'no'} new)", 10)

        # ── Phase 2: Listings ────────────────────────────────────────
        # Snapshot states before listing scan to detect changes
        state_before = dict(conn.execute(
            "SELECT pretty_id, request_state FROM requests"
        ).fetchall())

        _send(q, "listings", "Scanning request listings...", 12)
        before_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        scraper.phase2_listings()
        after_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        new_count = after_req - before_req

        # Detect records whose status changed during listing scan
        state_after = dict(conn.execute(
            "SELECT pretty_id, request_state FROM requests"
        ).fetchall())
        changed_ids = {pid for pid, st in state_after.items()
                       if pid in state_before and state_before[pid] != st}

        _send(q, "listings_done", f"Found {new_count} new requests ({after_req} total)", 35, new_requests=new_count)

        # ── Phase 3: Details ─────────────────────────────────────────
        # Detect records marked scraped but with incomplete data
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

        # Scrape: new/unscraped + incomplete + non-closed + status-changed
        TERMINAL = ('closed', 'completed')
        new_ids = conn.execute(
            "SELECT pretty_id FROM requests WHERE detail_scraped=0"
        ).fetchall()
        new_set = {r[0] for r in new_ids} | incomplete_ids

        active_ids = conn.execute(
            "SELECT pretty_id FROM requests WHERE detail_scraped=1"
        ).fetchall()
        refresh_set = {r[0] for r in active_ids
                       if state_after.get(r[0], '').lower() not in TERMINAL}
        refresh_set |= changed_ids  # also re-scrape any status-changed records

        all_ids = sorted(new_set | refresh_set)
        total = len(all_ids)
        n_new = len(new_set)
        n_refresh = len(refresh_set - new_set)

        if total == 0:
            _send(q, "details", "All requests up to date", 65)
        else:
            label = []
            if n_new:
                label.append(f"{n_new} new")
            if n_refresh:
                label.append(f"{n_refresh} to refresh")
            _send(q, "details", f"Scraping details ({', '.join(label)})...", 37)
            for i, pretty_id in enumerate(all_ids):
                progress = 37 + int(((i + 1) / total) * 28)  # 37→65
                tag = "new" if pretty_id in new_set else "refresh"
                _send(q, "details", f"Scraping {pretty_id} [{tag}] ({i + 1}/{total})...",
                      progress, current=i + 1, total=total)
                try:
                    scraper._scrape_one(pretty_id)
                    conn.execute(
                        "UPDATE requests SET detail_scraped=1 WHERE pretty_id=?",
                        (pretty_id,))
                except Exception as e:
                    conn.execute(
                        "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                        ("error", f"{pretty_id}: {e}"))
                time.sleep(DELAY_API)
                if (i + 1) % 50 == 0:
                    conn.commit()
            conn.commit()

        # ── Phase 4: Download documents ──────────────────────────────
        pending = conn.execute("""
            SELECT id, request_pretty_id, title, asset_url
            FROM documents WHERE downloaded=0
            ORDER BY request_pretty_id
        """).fetchall()
        doc_total = len(pending)

        if doc_total == 0:
            _send(q, "downloads", "No documents to download", 95)
        else:
            _send(q, "downloads", f"Downloading {doc_total} documents...", 67)
            dl_ok = dl_fail = 0

            for j, (doc_id, pretty_id, title, asset_url) in enumerate(pending):
                progress = 67 + int(((j + 1) / doc_total) * 28)  # 67→95
                _send(q, "downloads",
                      f"Downloading {title or f'doc {doc_id}'} ({j + 1}/{doc_total})...",
                      progress, current=j + 1, total=doc_total)

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
                    from pathlib import Path
                    req_dir = DOCS_DIR / pretty_id
                    req_dir.mkdir(parents=True, exist_ok=True)

                    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_',
                                  title or f'doc_{doc_id}')
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
            _send(q, "downloads_done", f"Documents: {', '.join(parts)}", 95)

        # ── Phase 5: Convert document previews ─────────────────────
        from app.config import CONVERTIBLE_EXTENSIONS, SOFFICE_PATH
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
                from app.config import BASE_DIR
                fp = BASE_DIR / fp
            cache = fp.parent / (fp.name + ".preview.pdf")
            if fp.exists() and not cache.exists():
                to_convert.append((doc_id, title, ext, fp, cache))

        if to_convert:
            _send(q, "converting", f"Converting {len(to_convert)} documents to PDF...", 93)
            cv_ok = cv_fail = 0
            for k, (doc_id, title, ext, fp, cache) in enumerate(to_convert):
                _send(q, "converting",
                      f"Converting {title or f'doc {doc_id}'} ({k+1}/{len(to_convert)})...",
                      93 + int(((k+1) / len(to_convert)) * 2))  # 93→95
                try:
                    if convert_to_pdf(fp, cache, timeout=180):
                        cv_ok += 1
                    else:
                        cv_fail += 1
                except Exception:
                    cv_fail += 1
            parts_cv = [f"{cv_ok} converted"]
            if cv_fail:
                parts_cv.append(f"{cv_fail} failed")
            _send(q, "converting_done", f"Previews: {', '.join(parts_cv)}", 95)

        # ── Phase 6: Transcribe audio/video ──────────────────────────
        from app.services.transcription import is_civic_media_available, transcribe_document, get_untranscribed_documents

        if is_civic_media_available():
            untranscribed = get_untranscribed_documents(conn)
            tr_total = len(untranscribed)
            if tr_total == 0:
                _send(q, "transcribing", "No audio/video files to transcribe", 99)
            else:
                _send(q, "transcribing", f"Transcribing {tr_total} audio/video files...", 96)
                tr_ok = tr_fail = 0
                for k, doc in enumerate(untranscribed):
                    progress = 96 + int(((k + 1) / tr_total) * 3)  # 96→99
                    doc_label = doc['title'] or f"doc {doc['id']}"
                    _send(q, "transcribing",
                          f"Transcribing {doc_label} ({k+1}/{tr_total})...",
                          progress, current=k + 1, total=tr_total)
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
                _send(q, "transcribing_done", f"Transcriptions: {', '.join(parts_tr)}", 99)
        else:
            _send(q, "transcribing", "Skipping transcription (civic_media not running)", 99)

        # ── Done ─────────────────────────────────────────────────────
        final_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        final_new = final_req - before_req
        parts = []
        if final_new:
            parts.append(f"{final_new} new requests")
        if n_refresh:
            parts.append(f"{n_refresh} refreshed")
        if doc_total:
            parts.append(f"{doc_total} documents processed")
        summary = ", ".join(parts) if parts else "everything up to date"
        conn.execute(
            "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
            ("pull_complete", summary))
        conn.commit()
        conn.close()
        _send(q, "done", f"Complete: {summary} ({final_req} total requests)", 100)

    except Exception as e:
        _send(q, "error", f"Scrape failed: {e}", -1)
    finally:
        q.put(None)  # sentinel to end SSE stream


@router.get("/run")
async def run_scrape():
    if not _lock.acquire(blocking=False):
        async def already_running():
            msg = {"phase": "error", "message": "A scrape is already in progress", "progress": -1}
            yield f"data: {json.dumps(msg)}\n\n"
        return StreamingResponse(already_running(), media_type="text/event-stream")

    q = queue.Queue()

    def thread_target():
        try:
            _worker(q)
        finally:
            _lock.release()

    thread = threading.Thread(target=thread_target, daemon=True)
    thread.start()

    async def event_stream():
        loop = asyncio.get_event_loop()
        while True:
            try:
                msg = await loop.run_in_executor(
                    None, lambda: q.get(timeout=300))
                if msg is None:
                    break
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'phase': 'error', 'message': 'Timeout waiting for scraper', 'progress': -1})}\n\n"
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
