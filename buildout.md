# Shasta County PRA Backup — Searchable Database Frontend

## Project Goal

Build a local web-based interface to browse, search, and analyze the complete backup of Shasta County's NextRequest public records portal (https://shastacountyca.nextrequest.com/requests/). This is a civic journalism tool for accountability reporting.

## What Already Exists

A Python scraper (`scraper.py`) has already collected all data into a SQLite database at:

```
E:\0-Automated-Apps\Shasta-PRA-Backup\shasta_nextrequest_backup\nextrequest.db
```

### Database Schema

```sql
-- 1,306 public records requests
CREATE TABLE requests (
    pretty_id TEXT PRIMARY KEY,          -- e.g. "26-309", "25-389"
    numeric_id INTEGER,                  -- internal NextRequest ID (e.g. 3651177)
    request_text TEXT,                   -- plain text version
    request_text_html TEXT,              -- original HTML
    request_state TEXT,                  -- "Closed", "Open", "Overdue", etc.
    visibility TEXT,                     -- "published"
    request_date TEXT,                   -- "February 20, 2026" (from detail) or "02/20/2026" (from listing)
    due_date TEXT,
    closed_date TEXT,
    request_submit_type TEXT,            -- "In person", "Email", "Online", etc.
    anticipated_fulfilled_at TEXT,
    expiration_date TEXT,
    exempt_from_retention INTEGER,
    department_names TEXT,               -- comma-separated: "County Counsel, Sheriff-Coroner"
    departments_json TEXT,               -- JSON array: [{"id":24936,"name":"County Counsel","poc_id":2186863}]
    poc_id INTEGER,                      -- point of contact ID
    poc_name TEXT,                       -- "Miranda Angel", "Josh Fugitt", etc.
    requester_id INTEGER,
    requester_name TEXT,                 -- often null (redacted on public portal)
    requester_email TEXT,                -- often null
    requester_company TEXT,              -- often null
    staff_cost TEXT,
    request_staff_hours TEXT,
    request_field_values TEXT,           -- JSON
    page_url TEXT,                       -- full URL to original request
    raw_list_json TEXT,                  -- complete JSON from listing API
    raw_detail_json TEXT,                -- complete JSON from detail API
    scraped_at TEXT,
    detail_scraped INTEGER DEFAULT 0     -- 1 = detail+timeline+docs fetched
);

-- Timeline events for each request (status changes, messages, closures)
CREATE TABLE timeline_events (
    timeline_id INTEGER PRIMARY KEY,
    request_pretty_id TEXT NOT NULL,
    timeline_name TEXT,                  -- "Request Closed", "Department Assignment", "Request Published", etc.
    timeline_display_text TEXT,          -- HTML content (closure messages, notes)
    timeline_state TEXT,                 -- "Anyone with access to this request"
    timeline_byline TEXT,               -- "February 20, 2026, 10:15am by Staff"
    timeline_icon_class TEXT,           -- "far fa-check-square", "fas fa-university", etc.
    timeline_is_collapsable INTEGER,
    timeline_is_pinned INTEGER,
    raw_json TEXT
);

-- Documents/files attached to requests
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,              -- e.g. 46180464
    request_pretty_id TEXT NOT NULL,
    request_numeric_id INTEGER,
    title TEXT,                          -- "1 News PRA.pdf", "5 Sinner report cont._PRA Redacted.pdf"
    file_extension TEXT,                 -- "pdf", "docx", "xlsx", etc.
    file_size_mb REAL,                   -- from document_scan.file_size (e.g. 0.482)
    file_size_bytes INTEGER,             -- populated after download
    upload_date TEXT,                    -- "Uploaded: 05/29/2025"
    upload_date_iso TEXT,               -- "2025-05-29T12:07:49.496-07:00"
    visibility TEXT,                     -- "Public"
    review_state TEXT,                   -- "Unprocessed"
    asset_url TEXT,                      -- "//nextrequestdev.s3.amazonaws.com/shastacountyca/25-389/..."
    folder_name TEXT,
    subfolder_name TEXT,
    local_path TEXT,                     -- local file path after download
    downloaded INTEGER DEFAULT 0,
    sha256 TEXT,
    raw_json TEXT
);

-- All county departments
CREATE TABLE departments (
    id INTEGER PRIMARY KEY,              -- e.g. 24936
    name TEXT,                           -- "County Counsel", "Sheriff-Coroner", etc.
    poc_id INTEGER,
    raw_json TEXT
);

-- Scraper activity log
CREATE TABLE scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT,
    detail TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);
```

### Sample Data (from API probing)

**Request listing item:**
```json
{
  "request_date": "02/20/2026",
  "staff_cost": "0.0",
  "visibility": "Published",
  "id": "26-309",
  "request_state": "Closed",
  "department_names": "Clerk of the Board, County Counsel",
  "due_date": "03/02/2026",
  "poc_name": "Miranda Angel",
  "request_path": "/requests/26-309",
  "request_text": "On February 20, 2026, Shasta County Supervisor..."
}
```

**Request detail:**
```json
{
  "pretty_id": "25-389",
  "request_text": "<p>HTML formatted request text...</p>",
  "request_state": "Closed",
  "request_submit_type": "Email",
  "request_date": "May 13, 2025",
  "department_names": "County Counsel, Sheriff-Coroner",
  "departments": [{"id": 24936, "name": "County Counsel", "poc_id": 2186863}],
  "poc": {"id": 1434387, "email_or_name": "Staff Name"},
  "requester": {"id": 1541040, "name": null, "email": null}
}
```

**Document item:**
```json
{
  "request_id": 3651177,
  "id": 46180464,
  "title": "1 News PRA.pdf",
  "review_state": "Unprocessed",
  "asset_url": "//nextrequestdev.s3.amazonaws.com/shastacountyca/25-389/09fc7128-707b-4986-99c8-53a291bee570.pdf",
  "file_extension": "pdf",
  "visibility": "Public",
  "upload_date": "Uploaded: 05/29/2025",
  "folder_name": "",
  "document_scan": {
    "file_size": 0.482,
    "file_type": "pdf",
    "upload_date": "2025-05-29T12:07:49.496-07:00"
  }
}
```

**Timeline event:**
```json
{
  "timeline_id": 99906575,
  "timeline_icon_class": "far fa-check-square",
  "timeline_name": "Request Closed",
  "timeline_display_text": "<p>Please consider this as a final response...</p>",
  "timeline_state": "Anyone with access to this request",
  "timeline_byline": "February 20, 2026, 10:15am by Staff"
}
```

### Data Scale
- ~1,306 requests
- ~20+ departments
- Varying document counts (0 to 557 per request)
- Documents are primarily PDFs, stored locally in `shasta_nextrequest_backup/documents/{pretty_id}/`
- Total portal data: all public records requests from Shasta County, CA

## What I Want Built

A searchable, browsable local web interface for this database. Core requirements:

### 1. Dashboard / Overview
- Total requests, documents, departments
- Status breakdown (Open, Closed, Overdue, etc.)
- Requests over time (chart)
- Department distribution (chart)
- Recent requests

### 2. Request Browser
- Paginated table of all requests
- Sortable by: ID, date, status, department, POC
- Filterable by: status, department, POC, date range, submit type
- Full-text search across request_text
- Click into any request for detail view

### 3. Request Detail View
- Full request text (HTML formatted)
- Metadata sidebar: status, date, due date, departments, POC, submit type
- Timeline (chronological events with icons)
- Document list with:
  - Filename, type, size, upload date
  - Link to open locally downloaded file OR link to original NextRequest URL
  - Download status indicator
  - **Inline viewing via lightbox** for compatible file types:
    - PDFs: embedded PDF viewer
    - Images (JPG, PNG, GIF, BMP, WEBP): image preview
    - Videos (MP4, WEBM, MOV): video player with controls
    - Audio (MP3, WAV, OGG): audio player
    - Text files (TXT, CSV, JSON, XML): rendered in a code/text viewer
    - Unsupported types: fallback to download link
  - Clicking a document opens the lightbox overlay — closeable via X button, Escape key, or clicking outside

### 4. Department View
- List of all departments
- Request count per department
- Click into department to see all its requests

### 5. Search
- Full-text search across:
  - Request text
  - Timeline event text
  - Document titles
- Results grouped by request with snippets/highlights

### 6. Analytics (nice to have)
- Response time analysis (request_date to closure)
- Department workload comparison
- POC workload
- Requests with most documents
- Overdue requests

## Atlas Integration (Spoke API)

This project is a **spoke** in the Atlas hub-and-spoke ecosystem. Atlas (`E:\0-Automated-Apps\Atlas`) is the central orchestration hub that routes LLM queries across spoke apps.

### Spoke Registration

- **Spoke key**: `shasta_pra`
- **Name**: `Shasta PRA`
- **Port**: `8845`
- **Health check**: `GET /health`

### Existing Spokes (for reference)

| Spoke | Port | Project |
|---|---|---|
| civic_media | 8000 | `E:\0-Automated-Apps\civic_media` |
| article_tracker | 5000 | `E:\0-Automated-Apps\article-tracker` |
| shasta_db | 8844 | `E:\0-Automated-Apps\Shasta-DB` |
| facebook_offline | 8147 | `E:\0-Automated-Apps\Facebook-Offline` |
| **shasta_pra** | **8845** | **This project** |

### Required API Endpoints (for Atlas tool calls)

Atlas LLM tools map to these JSON API endpoints. All return JSON.

```
GET /health
    → {"status": "ok", "requests": 1306, "documents": 55}

GET /api/requests?q=&status=&department=&poc=&date_from=&date_to=&limit=20&offset=0
    → [{ pretty_id, request_state, request_text (truncated), department_names,
         poc_name, request_date, due_date, doc_count }]

GET /api/requests/{pretty_id}
    → { pretty_id, request_text, request_text_html, request_state, request_date,
        due_date, closed_date, department_names, poc_name, request_submit_type,
        timeline: [...], documents: [...] }

GET /api/departments
    → [{ id, name, request_count }]

GET /api/departments/{id}/requests?limit=20&offset=0
    → [{ pretty_id, request_state, request_text (truncated), request_date, poc_name }]

GET /api/search?q=&limit=20
    → { requests: [...], timeline_events: [...], documents: [...] }
    Full-text search across all tables, results grouped by type with snippets.

GET /api/stats
    → { total_requests, total_documents, total_departments, status_breakdown,
        department_breakdown, requests_by_month }

GET /api/documents/{doc_id}/file
    → Serves the local file (for inline viewing / lightbox)
```

### Atlas Tool Definitions (to be added to Atlas)

These LLM function-calling tools will be registered in Atlas:

- **`search_pra_requests`** — Search public records requests by keyword, status, department, or date range
- **`get_pra_request`** — Get full detail for a specific PRA request including timeline and documents
- **`list_pra_departments`** — List all county departments with request counts
- **`get_pra_stats`** — Get overview statistics about the PRA database
- **`search_pra_all`** — Full-text search across requests, timeline events, and document titles

### ChromaDB / RAG Integration

Atlas's LazyChroma RAG system will fetch from `GET /api/requests?q=&limit=50` to get candidate records for semantic search. The response format must include:

```json
[{
  "pretty_id": "26-309",
  "request_text": "Full request text for embedding...",
  "department_names": "County Counsel, Sheriff-Coroner",
  "poc_name": "Miranda Angel",
  "request_date": "02/20/2026",
  "request_state": "Closed"
}]
```

Atlas will chunk the `request_text` field, embed it via Ollama (`nomic-embed-text`), and store in ChromaDB with metadata: `source_type="shasta_pra"`, `source_id=pretty_id`, `date=request_date`.

### Integration Rules

1. This app must remain **independently functional** — it works on its own without Atlas.
2. **No spoke-to-spoke dependencies.** All cross-app communication goes through Atlas.
3. API endpoints should be general-purpose and useful standalone.
4. If modifying or removing an API endpoint that Atlas depends on, **stop and warn** before proceeding.

## Technical Preferences

- **Local-first**: Runs on my Windows machine, no external hosting needed
- **Python backend**: FastAPI serving the SQLite database on port **8845**
- **Frontend**: Clean, modern — could be server-rendered templates (Jinja2) or a simple React/Vue SPA
- **No authentication needed**: This is a local research tool
- **The database already exists** — the app just reads from it
- **Working directory**: `E:\0-Automated-Apps\Shasta-PRA-Backup\`
- **Python venv already set up** at `E:\0-Automated-Apps\Shasta-PRA-Backup\venv\`
- **Existing dependencies**: requests, beautifulsoup4, lxml, tqdm

## File Structure

```
E:\0-Automated-Apps\Shasta-PRA-Backup\
├── venv\                              # Python virtual environment
├── scraper.py                         # Data collector (already built)
├── analyze.py                         # CLI analysis tool (already built)
├── probe.py                           # API test script
├── probe_docs.py                      # Document API test script
├── requirements.txt                   # requests, beautifulsoup4, lxml, tqdm
└── shasta_nextrequest_backup\
    ├── nextrequest.db                 # SQLite database (THE data source)
    ├── documents\                     # Downloaded files organized by request ID
    │   ├── 25-389\
    │   │   ├── 1 News PRA.pdf
    │   │   ├── 5 Sinner report cont._PRA Redacted.pdf
    │   │   └── ... (557 files)
    │   └── {pretty_id}\
    ├── raw_responses\                 # Raw JSON API responses
    └── scrape_stats.json
```

## Prompt for New Chat

Copy this into a new Claude chat:

---

I have a SQLite database containing all 1,306 public records requests scraped from Shasta County's NextRequest portal. I need a local web application to browse, search, and analyze this data. The database is at `E:\0-Automated-Apps\Shasta-PRA-Backup\shasta_nextrequest_backup\nextrequest.db`.

Please read the attached `buildout.md` for the complete database schema, sample data, and requirements. Build me a Python web app (Flask or FastAPI) with a clean frontend that provides: a dashboard with stats/charts, a searchable/filterable request browser, request detail pages with timelines and document lists, department views, and full-text search. This is a local civic journalism research tool — no auth needed.

The Python venv is already at `E:\0-Automated-Apps\Shasta-PRA-Backup\venv\`. The database and downloaded document files already exist.

---
