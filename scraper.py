#!/usr/bin/env python3
"""
Shasta County NextRequest Public Records Scraper v3 (FINAL)
============================================================
Backs up all public records requests and documents from:
https://shastacountyca.nextrequest.com/requests/

All API response structures confirmed via probing (Feb 21, 2026).

CONFIRMED ENDPOINTS:
  GET /client/requests?page_number=1&per_page=100&sort_field=id&sort_direction=desc
      -> {"total_count":1306, "requests":[{id:"26-309", request_state, request_text, ...}]}

  GET /client/requests/{pretty_id}
      -> {pretty_id, request_text (HTML), departments:[{id,name,poc_id}], poc:{id,email_or_name}, requester:{id,name,...}, ...}

  GET /client/requests/{pretty_id}/timeline?page_number=1
      -> {"total_count":5, "timeline":[{timeline_id, timeline_name, timeline_display_text, timeline_byline, timeline_state, ...}]}

  GET /client/request_documents?request_id={pretty_id}&page=1&per_page=100
      -> {"total_documents_count":557, "documents":[{id, title, asset_url, file_extension, visibility, upload_date, document_scan:{file_size, file_type, upload_date}, ...}]}

  GET /documents/{doc_id}/download
      -> 302 redirect to signed S3 URL (THE download method)

  GET /client/departments
      -> [{id, name, poc_id}, ...]

Usage:
    pip install requests beautifulsoup4 lxml tqdm
    python scraper.py                       # Full scrape
    python scraper.py --no-docs             # Metadata only (~25 min)
    python scraper.py --list-only           # Just listings (~2 min)
    python scraper.py --docs-only           # Download files only
    python scraper.py --resume-from 25-100  # Resume details from ID
"""

import argparse
import json
import os
import re
import sqlite3
import time
import hashlib
from datetime import datetime
from pathlib import Path

import requests as http_requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_URL = "https://shastacountyca.nextrequest.com"
OUTPUT_DIR = Path("shasta_nextrequest_backup")
DB_PATH = OUTPUT_DIR / "nextrequest.db"
DOCS_DIR = OUTPUT_DIR / "documents"
RAW_DIR = OUTPUT_DIR / "raw_responses"

# Rate limiting — be respectful
DELAY_API = 1.0          # between listing/detail API calls
DELAY_SUB = 0.3          # between timeline/doc sub-requests for one request
DELAY_DOWNLOAD = 0.75    # between file downloads
MAX_RETRIES = 3
RETRY_BACKOFF = 5

LISTING_PAGE_SIZE = 100
DOC_PAGE_SIZE = 100

# ─── Database ────────────────────────────────────────────────────────────────

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
            pretty_id TEXT PRIMARY KEY,
            numeric_id INTEGER,
            request_text TEXT,
            request_text_html TEXT,
            request_state TEXT,
            visibility TEXT,
            request_date TEXT,
            due_date TEXT,
            closed_date TEXT,
            request_submit_type TEXT,
            anticipated_fulfilled_at TEXT,
            expiration_date TEXT,
            exempt_from_retention INTEGER,
            department_names TEXT,
            departments_json TEXT,
            poc_id INTEGER,
            poc_name TEXT,
            requester_id INTEGER,
            requester_name TEXT,
            requester_email TEXT,
            requester_company TEXT,
            staff_cost TEXT,
            request_staff_hours TEXT,
            request_field_values TEXT,
            page_url TEXT,
            raw_list_json TEXT,
            raw_detail_json TEXT,
            scraped_at TEXT,
            detail_scraped INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS timeline_events (
            timeline_id INTEGER PRIMARY KEY,
            request_pretty_id TEXT NOT NULL,
            timeline_name TEXT,
            timeline_display_text TEXT,
            timeline_state TEXT,
            timeline_byline TEXT,
            timeline_icon_class TEXT,
            timeline_is_collapsable INTEGER,
            timeline_is_pinned INTEGER,
            raw_json TEXT,
            FOREIGN KEY (request_pretty_id) REFERENCES requests(pretty_id)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            request_pretty_id TEXT NOT NULL,
            request_numeric_id INTEGER,
            title TEXT,
            file_extension TEXT,
            file_size_mb REAL,
            file_size_bytes INTEGER,
            upload_date TEXT,
            upload_date_iso TEXT,
            visibility TEXT,
            review_state TEXT,
            asset_url TEXT,
            folder_name TEXT,
            subfolder_name TEXT,
            local_path TEXT,
            downloaded INTEGER DEFAULT 0,
            sha256 TEXT,
            raw_json TEXT,
            FOREIGN KEY (request_pretty_id) REFERENCES requests(pretty_id)
        );

        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY,
            name TEXT,
            poc_id INTEGER,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            detail TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_tl_req ON timeline_events(request_pretty_id);
        CREATE INDEX IF NOT EXISTS idx_doc_req ON documents(request_pretty_id);
        CREATE INDEX IF NOT EXISTS idx_doc_dl ON documents(downloaded);
        CREATE INDEX IF NOT EXISTS idx_req_detail ON requests(detail_scraped);
    """)
    conn.commit()
    return conn


# ─── API Client ──────────────────────────────────────────────────────────────

class API:
    def __init__(self):
        self.session = http_requests.Session()
        self.session.headers.update({
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/131.0.0.0 Safari/537.36'),
        })

    def init_session(self):
        """Load main page → session cookie + CSRF token."""
        print("  Initializing session...")
        self.session.headers['Accept'] = 'text/html,*/*'
        r = self.session.get(f"{BASE_URL}/requests", timeout=30)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, 'lxml')
        meta = soup.find('meta', {'name': 'csrf-token'})
        if meta:
            self.session.headers['X-CSRF-Token'] = meta['content']
            print("  ✅ Session ready")
        else:
            print("  ⚠️  No CSRF token found")

        self.session.headers['Accept'] = 'application/json, text/plain, */*'
        self.session.headers['X-Requested-With'] = 'XMLHttpRequest'

    def _get_json(self, path, params=None):
        """GET → JSON with retries."""
        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code == 200:
                    return r.json()
                elif r.status_code == 401:
                    print(f"\n  ⚠️  401 on {path} — refreshing session")
                    self.init_session()
                elif r.status_code == 429:
                    wait = RETRY_BACKOFF * (attempt + 1)
                    print(f"\n  ⚠️  Rate limited, waiting {wait}s")
                    time.sleep(wait)
                elif r.status_code == 404:
                    return None
                else:
                    print(f"\n  ⚠️  HTTP {r.status_code} on {path}")
            except Exception as e:
                print(f"\n  ⚠️  Error on {path}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF)
        return None

    # ── Confirmed endpoints ──────────────────────────────────────────

    def get_departments(self):
        # -> [{id, name, poc_id}, ...]
        return self._get_json("/client/departments")

    def get_requests_page(self, page=1):
        # -> {"total_count": N, "requests": [{id:"26-309", request_state, ...}]}
        return self._get_json("/client/requests", {
            'page_number': page,
            'per_page': LISTING_PAGE_SIZE,
            'sort_field': 'id',
            'sort_direction': 'desc',
        })

    def get_request_detail(self, pretty_id):
        # -> {pretty_id, request_text (HTML), departments:[{id,name,poc_id}], poc:{...}, ...}
        return self._get_json(f"/client/requests/{pretty_id}")

    def get_timeline(self, pretty_id, page=1):
        # -> {"total_count": N, "timeline": [{timeline_id, timeline_name, ...}]}
        return self._get_json(f"/client/requests/{pretty_id}/timeline",
                             {'page_number': page})

    def get_request_documents(self, pretty_id, page=1):
        # -> {"total_documents_count":N, "documents":[{id, title, asset_url, ...}]}
        return self._get_json("/client/request_documents", {
            'request_id': pretty_id,
            'page': page,
            'per_page': DOC_PAGE_SIZE,
        })

    def get_download_redirect(self, doc_id):
        """
        GET /documents/{doc_id}/download → 302 to signed S3 URL.
        Returns the signed URL string, or None.
        """
        url = f"{BASE_URL}/documents/{doc_id}/download"
        try:
            r = self.session.get(url, allow_redirects=False, timeout=30)
            if r.status_code == 302:
                return r.headers.get('Location', '')
            elif r.status_code == 200:
                # Maybe it served the file directly
                return url
            else:
                return None
        except Exception as e:
            print(f"\n  ⚠️  Download redirect error for doc {doc_id}: {e}")
            return None

    def download_file(self, url, dest_path, timeout=180):
        """Download file to disk. Returns (success, sha256, file_size)."""
        try:
            r = self.session.get(url, stream=True, timeout=timeout)
            r.raise_for_status()
            sha = hashlib.sha256()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
                    sha.update(chunk)
            return True, sha.hexdigest(), os.path.getsize(dest_path)
        except Exception as e:
            # Clean up partial file
            if dest_path.exists():
                dest_path.unlink()
            return False, str(e), 0


# ─── Scraper ─────────────────────────────────────────────────────────────────

class Scraper:
    def __init__(self, conn, api):
        self.conn = conn
        self.api = api

    def run(self, skip_docs=False, resume_from=None):
        self.api.init_session()
        time.sleep(1)
        self.phase1_departments()
        self.phase2_listings()
        self.phase3_details(resume_from)
        if not skip_docs:
            self.phase4_download()

    # ── Phase 1 ──────────────────────────────────────────────────────

    def phase1_departments(self):
        print("\n📋 Phase 1: Departments...")
        depts = self.api.get_departments()
        if not depts or not isinstance(depts, list):
            print("  ⚠️  No department data")
            return
        for d in depts:
            if isinstance(d, dict):
                self.conn.execute(
                    "INSERT OR REPLACE INTO departments (id,name,poc_id,raw_json) VALUES(?,?,?,?)",
                    (d.get('id'), d.get('name'), d.get('poc_id'), json.dumps(d)))
        self.conn.commit()
        print(f"  ✅ {len(depts)} departments")
        time.sleep(DELAY_API)

    # ── Phase 2 ──────────────────────────────────────────────────────

    def phase2_listings(self):
        print("\n📋 Phase 2: Request listings...")
        page = 1
        total = 0

        while True:
            data = self.api.get_requests_page(page)
            if not data:
                break

            total_count = data.get('total_count', 0)
            items = data.get('requests', [])
            if not items:
                break

            for item in items:
                # In listings, "id" is the pretty_id (e.g. "26-309")
                pretty_id = item.get('id', '')
                if not pretty_id:
                    continue

                # Insert new records (skip if already exists)
                self.conn.execute("""
                    INSERT OR IGNORE INTO requests
                    (pretty_id, request_text, request_state, visibility,
                     request_date, due_date, department_names, poc_name,
                     requester_name, staff_cost, page_url, raw_list_json, scraped_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    pretty_id,
                    item.get('request_text', ''),
                    item.get('request_state', ''),
                    item.get('visibility', ''),
                    item.get('request_date', ''),
                    item.get('due_date', ''),
                    item.get('department_names', ''),
                    item.get('poc_name', ''),
                    item.get('requester_name'),
                    item.get('staff_cost', ''),
                    f"{BASE_URL}{item.get('request_path', '/requests/' + pretty_id)}",
                    json.dumps(item),
                    datetime.now().isoformat(),
                ))

                # Update mutable listing fields on existing records
                # (captures status changes, new due dates, etc. without overwriting detail data)
                self.conn.execute("""
                    UPDATE requests SET
                        request_state = COALESCE(?, request_state),
                        due_date = COALESCE(?, due_date),
                        department_names = COALESCE(?, department_names),
                        poc_name = COALESCE(?, poc_name),
                        staff_cost = COALESCE(?, staff_cost),
                        raw_list_json = ?,
                        scraped_at = ?
                    WHERE pretty_id = ?
                """, (
                    item.get('request_state'),
                    item.get('due_date'),
                    item.get('department_names'),
                    item.get('poc_name'),
                    item.get('staff_cost'),
                    json.dumps(item),
                    datetime.now().isoformat(),
                    pretty_id,
                ))
                total += 1

            self.conn.commit()
            with open(RAW_DIR / f"listing_p{page}.json", 'w') as f:
                json.dump(data, f, indent=2)

            print(f"  Page {page}: {len(items)} items (total: {total}/{total_count})")

            if len(items) < LISTING_PAGE_SIZE:
                break
            page += 1
            time.sleep(DELAY_API)

        print(f"\n  ✅ {total} requests indexed")

    # ── Phase 3 ──────────────────────────────────────────────────────

    def phase3_details(self, resume_from=None):
        print("\n📄 Phase 3: Details + timelines + document lists...")

        # Detect records marked as scraped but with incomplete data
        incomplete = self.conn.execute("""
            SELECT r.pretty_id FROM requests r
            WHERE r.detail_scraped = 1 AND (
                r.raw_detail_json IS NULL
                OR r.request_text IS NULL OR r.request_text = ''
                OR r.departments_json IS NULL
                OR r.pretty_id NOT IN (
                    SELECT DISTINCT request_pretty_id FROM timeline_events
                )
            )
        """).fetchall()
        if incomplete:
            ids = [r[0] for r in incomplete]
            self.conn.executemany(
                "UPDATE requests SET detail_scraped=0 WHERE pretty_id=?",
                [(pid,) for pid in ids])
            self.conn.commit()
            print(f"  ⚠️  {len(ids)} records with incomplete data queued for re-scrape")

        if resume_from:
            rows = self.conn.execute(
                "SELECT pretty_id FROM requests WHERE pretty_id >= ? ORDER BY pretty_id",
                (resume_from,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT pretty_id FROM requests WHERE detail_scraped=0 ORDER BY pretty_id"
            ).fetchall()

        print(f"  {len(rows)} requests to process")

        for i, (pretty_id,) in enumerate(tqdm(rows, desc="Details")):
            try:
                self._scrape_one(pretty_id)
                self.conn.execute(
                    "UPDATE requests SET detail_scraped=1 WHERE pretty_id=?",
                    (pretty_id,))
            except Exception as e:
                self.conn.execute(
                    "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                    ("error", f"{pretty_id}: {e}"))

            time.sleep(DELAY_API)
            if (i + 1) % 50 == 0:
                self.conn.commit()
                tqdm.write(f"  💾 Checkpoint at {i+1}")

        self.conn.commit()

    def _scrape_one(self, pretty_id):
        """Fetch detail + timeline + document list for one request."""

        # ── Detail ───────────────────────────────────────────────
        d = self.api.get_request_detail(pretty_id)
        if d and isinstance(d, dict):
            depts = d.get('departments', [])
            poc = d.get('poc') or {}
            req = d.get('requester') or {}

            # Strip HTML from request_text for the plain-text column
            plain_text = BeautifulSoup(d.get('request_text', ''), 'lxml').get_text(separator='\n').strip()

            self.conn.execute("""
                UPDATE requests SET
                    numeric_id=?,
                    request_text=?,
                    request_text_html=?,
                    request_state=?,
                    visibility=?,
                    request_date=?,
                    due_date=COALESCE(?,due_date),
                    request_submit_type=?,
                    anticipated_fulfilled_at=?,
                    expiration_date=?,
                    exempt_from_retention=?,
                    department_names=?,
                    departments_json=?,
                    poc_id=?,
                    poc_name=?,
                    requester_id=?,
                    requester_name=?,
                    requester_email=?,
                    requester_company=?,
                    staff_cost=?,
                    request_staff_hours=?,
                    request_field_values=?,
                    raw_detail_json=?,
                    scraped_at=?
                WHERE pretty_id=?
            """, (
                # numeric_id comes from documents response (request_id field)
                None,
                plain_text,
                d.get('request_text', ''),
                d.get('request_state', ''),
                d.get('visibility', d.get('request_visibility', '')),
                d.get('request_date', ''),
                d.get('request_due_date'),
                d.get('request_submit_type', ''),
                d.get('anticipated_fulfilled_at'),
                d.get('expiration_date'),
                d.get('exempt_from_retention'),
                d.get('department_names', ''),
                json.dumps(depts),
                poc.get('id'),
                poc.get('email_or_name', ''),
                req.get('id'),
                req.get('name'),
                req.get('email'),
                req.get('company'),
                d.get('request_staff_cost', ''),
                json.dumps(d.get('request_staff_hours')),
                json.dumps(d.get('request_field_values', [])),
                json.dumps(d),
                datetime.now().isoformat(),
                pretty_id,
            ))

        time.sleep(DELAY_SUB)

        # ── Timeline ─────────────────────────────────────────────
        tl_page = 1
        while True:
            tl = self.api.get_timeline(pretty_id, page=tl_page)
            if not tl:
                break

            # Confirmed: {"total_count": N, "timeline": [...]}
            events = tl.get('timeline', [])
            if not events:
                break

            for ev in events:
                if not isinstance(ev, dict):
                    continue
                self.conn.execute("""
                    INSERT OR REPLACE INTO timeline_events
                    (timeline_id, request_pretty_id, timeline_name,
                     timeline_display_text, timeline_state, timeline_byline,
                     timeline_icon_class, timeline_is_collapsable,
                     timeline_is_pinned, raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                """, (
                    ev.get('timeline_id'),
                    pretty_id,
                    ev.get('timeline_name', ''),
                    ev.get('timeline_display_text', ''),
                    ev.get('timeline_state', ''),
                    ev.get('timeline_byline', ''),
                    ev.get('timeline_icon_class', ''),
                    ev.get('timeline_is_collapsable', False),
                    ev.get('timeline_is_pinned', False),
                    json.dumps(ev),
                ))

            total_tl = tl.get('total_count', 0)
            if tl_page * len(events) >= total_tl or len(events) == 0:
                break
            tl_page += 1
            time.sleep(DELAY_SUB)

        time.sleep(DELAY_SUB)

        # ── Documents ────────────────────────────────────────────
        # Confirmed: request_id param accepts pretty_id like "25-389"
        doc_page = 1
        while True:
            resp = self.api.get_request_documents(pretty_id, page=doc_page)
            if not resp:
                break

            # Confirmed: {"total_documents_count":N, "documents":[...]}
            total_docs = resp.get('total_documents_count', 0)
            docs = resp.get('documents', [])
            if not docs:
                break

            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                doc_id = doc.get('id')
                if not doc_id:
                    continue

                scan = doc.get('document_scan') or {}

                # Update numeric_id on the request if we haven't yet
                numeric_rid = doc.get('request_id')
                if numeric_rid:
                    self.conn.execute(
                        "UPDATE requests SET numeric_id=? WHERE pretty_id=? AND numeric_id IS NULL",
                        (numeric_rid, pretty_id))

                self.conn.execute("""
                    INSERT OR REPLACE INTO documents
                    (id, request_pretty_id, request_numeric_id, title,
                     file_extension, file_size_mb, upload_date, upload_date_iso,
                     visibility, review_state, asset_url,
                     folder_name, subfolder_name, raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    doc_id,
                    pretty_id,
                    doc.get('request_id'),
                    doc.get('title', ''),
                    doc.get('file_extension', ''),
                    scan.get('file_size'),           # e.g. 0.482 (MB)
                    doc.get('upload_date', ''),       # "Uploaded: 05/29/2025"
                    scan.get('upload_date', ''),      # ISO: "2025-05-29T12:07:49.496-07:00"
                    doc.get('visibility', ''),        # "Public"
                    doc.get('review_state', ''),
                    doc.get('asset_url', ''),         # "//nextrequestdev.s3.amazonaws.com/..."
                    doc.get('folder_name', ''),
                    doc.get('subfolder_name', ''),
                    json.dumps(doc),
                ))

            if len(docs) < DOC_PAGE_SIZE or doc_page * DOC_PAGE_SIZE >= total_docs:
                break
            doc_page += 1
            time.sleep(DELAY_SUB)

    # ── Phase 4 ──────────────────────────────────────────────────────

    def phase4_download(self):
        print("\n📥 Phase 4: Downloading documents...")

        pending = self.conn.execute("""
            SELECT id, request_pretty_id, title, asset_url
            FROM documents WHERE downloaded=0
            ORDER BY request_pretty_id
        """).fetchall()

        if not pending:
            print("  No documents to download.")
            return

        print(f"  {len(pending)} documents to download")
        ok = fail = skip = 0

        for doc_id, pretty_id, title, asset_url in tqdm(pending, desc="Downloading"):
            # PRIMARY method: /documents/{id}/download → 302 → signed S3 URL
            signed_url = self.api.get_download_redirect(doc_id)

            if not signed_url:
                # FALLBACK: try the asset_url with https: prefix
                if asset_url:
                    signed_url = "https:" + asset_url if asset_url.startswith("//") else asset_url

            if not signed_url:
                fail += 1
                self.conn.execute(
                    "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                    ("no_url", f"doc {doc_id} ({title}) for {pretty_id}"))
                continue

            try:
                req_dir = DOCS_DIR / pretty_id
                req_dir.mkdir(parents=True, exist_ok=True)

                # Sanitize filename
                safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title or f'doc_{doc_id}')
                if not safe.strip():
                    safe = f"document_{doc_id}"
                path = req_dir / safe

                # Handle duplicate filenames
                if path.exists():
                    stem, ext = path.stem, path.suffix
                    c = 1
                    while path.exists():
                        path = req_dir / f"{stem}_{c}{ext}"
                        c += 1

                success, sha_or_err, size = self.api.download_file(signed_url, path)

                if success:
                    self.conn.execute("""
                        UPDATE documents
                        SET downloaded=1, local_path=?, sha256=?, file_size_bytes=?
                        WHERE id=?
                    """, (str(path), sha_or_err, size, doc_id))
                    ok += 1
                else:
                    fail += 1
                    self.conn.execute(
                        "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                        ("download_fail", f"doc {doc_id} ({title}): {sha_or_err}"))

            except Exception as e:
                fail += 1
                self.conn.execute(
                    "INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                    ("download_error", f"doc {doc_id}: {e}"))

            time.sleep(DELAY_DOWNLOAD)
            if (ok + fail) % 100 == 0:
                self.conn.commit()

        self.conn.commit()
        print(f"\n  ✅ Downloaded: {ok}")
        if fail:
            print(f"  ⚠️  Failed: {fail}")

    def download_only(self):
        self.api.init_session()
        self.phase4_download()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape Shasta County NextRequest public records portal")
    parser.add_argument('--no-docs', action='store_true',
                       help="Skip document downloads (metadata only)")
    parser.add_argument('--docs-only', action='store_true',
                       help="Only download documents for already-scraped requests")
    parser.add_argument('--resume-from', type=str,
                       help="Resume detail scraping from this ID (e.g. 25-100)")
    parser.add_argument('--list-only', action='store_true',
                       help="Only fetch request listings (fastest)")
    parser.add_argument('--full-rescrape', action='store_true',
                       help="Re-scrape details for ALL requests, not just unscraped ones")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    conn = init_db(DB_PATH)
    conn.execute("INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                 ("start", json.dumps(vars(args))))
    conn.commit()

    api = API()
    scraper = Scraper(conn, api)

    print("=" * 60)
    print("  Shasta County NextRequest Scraper v3")
    print(f"  Target:   {BASE_URL}")
    print(f"  Database: {DB_PATH.absolute()}")
    print("=" * 60)

    if args.full_rescrape:
        count = conn.execute("SELECT COUNT(*) FROM requests WHERE detail_scraped=1").fetchone()[0]
        conn.execute("UPDATE requests SET detail_scraped=0")
        conn.commit()
        print(f"  Reset {count} records for full re-scrape")

    if args.docs_only:
        scraper.download_only()
    elif args.list_only:
        api.init_session()
        scraper.phase1_departments()
        scraper.phase2_listings()
    else:
        scraper.run(skip_docs=args.no_docs, resume_from=args.resume_from)

    # Stats
    print("\n" + "=" * 60)
    stats = {
        'requests': conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
        'details_scraped': conn.execute("SELECT COUNT(*) FROM requests WHERE detail_scraped=1").fetchone()[0],
        'timeline_events': conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0],
        'documents_listed': conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        'documents_downloaded': conn.execute("SELECT COUNT(*) FROM documents WHERE downloaded=1").fetchone()[0],
        'departments': conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0],
        'errors': conn.execute("SELECT COUNT(*) FROM scrape_log WHERE action IN ('error','download_fail','download_error','no_url')").fetchone()[0],
    }
    for k, v in stats.items():
        print(f"  {k:.<40} {v}")

    with open(OUTPUT_DIR / "scrape_stats.json", 'w') as f:
        json.dump({**stats, 'completed_at': datetime.now().isoformat()}, f, indent=2)

    conn.execute("INSERT INTO scrape_log (action,detail) VALUES(?,?)",
                 ("complete", json.dumps(stats)))
    conn.commit()
    conn.close()
    print(f"\n  📁 {DB_PATH.absolute()}")
    print("🎉 Done!")


if __name__ == "__main__":
    main()
