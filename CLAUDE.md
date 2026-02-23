# Shasta PRA Backup

Local web app + Atlas spoke for browsing Shasta County public records requests scraped from the NextRequest portal.

## Quick Start

```
python start.py
# → http://127.0.0.1:8845
```

## Stack

- **Backend:** FastAPI + sync SQLAlchemy engine + Pydantic v2
- **Frontend:** Vanilla HTML/JS + Chart.js (no build step)
- **Database:** SQLite (read-only, created by scraper.py)
- **Port:** 8845

## Architecture

```
app/
├── main.py           # FastAPI app, page routes, health, static mount
├── config.py         # DB path, docs dir, port
├── database.py       # Sync SQLAlchemy engine + get_db() dependency
├── schemas.py        # Pydantic response models
├── routers/          # API endpoints under /api/
│   ├── requests.py   # /api/requests
│   ├── departments.py # /api/departments
│   ├── search.py     # /api/search
│   ├── stats.py      # /api/stats
│   └── documents.py  # /api/documents/{id}/file
├── services/
│   └── transcription.py  # Whisper transcription client (calls civic_media)
└── static/           # Frontend HTML/JS/CSS
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check with record counts |
| GET | `/api/requests` | List/filter requests (q, status, department, poc, date_from, date_to, sort, limit, offset) |
| GET | `/api/requests/{pretty_id}` | Request detail with timeline + documents |
| GET | `/api/departments` | All departments with request counts |
| GET | `/api/departments/{id}/requests` | Requests for a department |
| GET | `/api/search?q=` | Full-text search across all tables |
| GET | `/api/stats` | Aggregate statistics |
| GET | `/api/documents` | List/filter documents (q, ext, date_from, date_to, sort, limit, offset) |
| GET | `/api/documents/extensions` | File type counts for filter dropdown |
| GET | `/api/documents/{id}/file` | Serve original downloaded document |
| GET | `/api/documents/{id}/preview` | Preview with on-demand conversion (PDF/images inline, Office→PDF) |
| GET | `/api/documents/transcription-status` | Transcription summary: total, transcribed, pending, failed |
| GET | `/api/documents/{id}/transcript` | Get stored transcription (text + segments with timestamps) |
| POST | `/api/documents/{id}/transcribe` | Manual trigger — sends file to civic_media for Whisper transcription |

## Database

SQLite at `shasta_nextrequest_backup/nextrequest.db`. Tables: `requests`, `timeline_events`, `documents`, `departments`, `scrape_log`, `document_text`, `processing_log`. Schema created by `scraper.py` (raw sqlite3, not ORM). All API access is read-only via parameterized `text()` queries.

## Document Processing Pipeline

Documents go through three post-download processing stages. All run automatically during scrape and have standalone batch scripts for backfilling.

### 1. LibreOffice PDF Conversion (Office docs → inline preview)

Converts Office documents (DOCX, DOC, XLSX, XLS, PPTX, PPT, ODT, ODS, ODP, RTF) to PDF for browser-native preview display.

**How it works:**
- Uses LibreOffice headless: `soffice --headless --convert-to pdf --outdir <tmpdir> <source>`
- Converts in a temp directory, then copies result alongside the original as `{filename}.preview.pdf`
- Cross-drive safe: uses `shutil.copy2()` instead of `Path.replace()` (Windows C:→E: issue)
- Preview endpoint serves cached PDF; creates on-demand if missing (with 50 MB size guard)

**Key files:**
- `app/config.py` — `SOFFICE_PATH` (auto-detects local portable or Program Files install), `CONVERTIBLE_EXTENSIONS` set
- `app/routers/documents.py` — `convert_to_pdf(source, cache_path, timeout=120)` reusable function
- `convert_previews.py` — Batch script: `python convert_previews.py [--force] [--dry-run]`
- `app/routers/scrape.py` — Phase 5: auto-converts after document downloads

**LibreOffice install:** `winget install --id TheDocumentFoundation.LibreOffice` (or portable via `setup_libreoffice.py`)

**File naming:** `documents/24-4/report.docx` → `documents/24-4/report.docx.preview.pdf`

### 2. Whisper Transcription (Audio/Video → searchable text)

Transcribes audio/video documents (MP4, MKV, M4A, WAV, etc.) via civic_media's faster-whisper GPU endpoint.

**How it works:**
- Sends file to `POST http://127.0.0.1:8000/api/transcribe` (civic_media)
- civic_media extracts audio (ffmpeg → 16kHz mono WAV), runs faster-whisper large-v3 on GPU
- Returns full text + timestamped segments; stored in `document_text` table
- If civic_media is down, skips gracefully — manual trigger available in lightbox UI

**Key files:**
- `app/config.py` — `CIVIC_MEDIA_URL`, `TRANSCRIBABLE_EXTENSIONS`, timeout settings
- `app/services/transcription.py` — `is_civic_media_available()`, `transcribe_document()`, `get_untranscribed_documents()`
- `app/routers/documents.py` — `POST /{id}/transcribe` (manual), `GET /{id}/transcript`, `GET /transcription-status`
- `app/routers/scrape.py` — Phase 6: auto-transcribes after document downloads
- `transcribe_documents.py` — Batch script: `python transcribe_documents.py [--force] [--dry-run] [--limit N]`
- `app/static/lightbox.js` — Transcript display below audio/video player in lightbox

**Database:** `document_text` table (shared with OCR), `processing_log` for status tracking

**Search:** `document_text.text_content` is included in `/api/search` results

### 3. OCR & Text Extraction (planned)

Extracts text from all documents for full-text search and creates searchable PDFs for scanned documents.

**Tech stack:** PyMuPDF (fitz) + EasyOCR (handles handwriting)

**Processing strategy:**
| Type | Method |
|------|--------|
| PDF with native text | PyMuPDF text extraction |
| Scanned/image PDF | Render pages → EasyOCR → store text + create `.searchable.pdf` with invisible text overlay |
| Mixed PDF | Per-page: native where available, OCR where scanned |
| Office docs | Extract from existing `.preview.pdf` via PyMuPDF |
| TXT, CSV | Read directly |
| JPG, PNG, TIF | EasyOCR on image |

**Database:** `document_text` table (per-page, with FTS5 index) + `ocr_processing_log` for resume capability

**Batch script:** `python ocr_documents.py [--force] [--dry-run] [--pdf-only] [--limit N]`

**File naming:** `documents/24-4/scan.pdf` → `documents/24-4/scan.pdf.searchable.pdf`

### Reusable Patterns for Other Projects

All processing stages follow the same pattern:
1. **Reusable function** in a router/module (`convert_to_pdf()`, `transcribe_document()`, `process_document()`)
2. **Standalone batch script** for backfill with `--force`, `--dry-run`, progress reporting
3. **Post-scrape SSE phase** in `scrape.py` for auto-processing new downloads
4. **Cache file alongside original** with naming convention: `{original}.{purpose}.{ext}`
5. **Processing log table** for resume capability (skip already-processed on re-run)
6. **Size/page guards** to prevent runaway on large files

## Atlas Integration

Spoke key: `shasta_pra`. Registered in Atlas config on port 8845. Tools: `search_pra_requests`, `get_pra_request`, `list_pra_departments`, `get_pra_stats`, `search_pra_all`. RAG chunking uses metadata prefix + sliding window.

## Conventions

- Sync SQLAlchemy (not async) — matches civic_media pattern
- Raw `text()` queries, not ORM models — schema is externally created
- All API responses go through Pydantic schemas
- Frontend: each page has its own `.html` + `.js` pair, shared utilities in `app.js`
- Path traversal protection on document serving
- Dates in DB are `MM/DD/YYYY`, but API responses return ISO `YYYY-MM-DD` via Pydantic validators. Date range filtering in SQL uses `substr()` for comparison against raw DB values. API consumers always receive ISO dates.

## Master Schema Reference

**`E:\0-Automated-Apps\MASTER_SCHEMA.md`** contains the canonical cross-project
database schema. If you add, remove, or modify any database tables or fields in
this project, **you must update the Master Schema** to keep it in sync. The agent
is authorized and encouraged to edit that file directly.

**`E:\0-Automated-Apps\MASTER_PROJECT.md`** describes the overall ecosystem
architecture and how all projects interconnect.
