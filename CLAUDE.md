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

### 3. OCR & Text Extraction — COMPLETE

Extracts text from all documents for full-text search. 3-stage pipeline per `VISION_PIPELINE.md`.

**Tech stack:** PyMuPDF (Stage 1) → Surya OCR GPU (Stage 2) → VLM description (Stage 3)

**Processing strategy:**
| Type | Stage | Method |
|------|-------|--------|
| PDF with native text | 1 | PyMuPDF |
| Scanned/image PDF | 1→2 | PyMuPDF per-page → Surya fallback for pages < 50 chars |
| Office docs | 1→2 | Extract from `.preview.pdf` via same PDF path |
| TXT, CSV | 1 | Direct read |
| JPG, PNG, TIF | 2 | Surya directly |
| Photos, maps, diagrams (no text) | 3 | VLM description via Mission Control |

**Key files:**
- `app/services/ocr.py` — Stages 1+2: PyMuPDF + Surya subprocess
- `app/services/vision.py` — Stage 3: VLM via MC (`vision_model` class), Ollama fallback
- `scripts/surya_worker.py` — Surya worker running in civic_media's Python 3.11 venv
- `ocr_documents.py` — Batch OCR: `python ocr_documents.py [--force] [--dry-run] [--limit N]`
- `describe_documents.py` — Batch VLM: `python describe_documents.py [--test] [--dry-run] [--limit N]`

**Surya:** Installed in `civic_media/venv` (GPU PyTorch, RTX 5090). Called via subprocess
to avoid Python 3.13/3.11 ABI incompatibility. See `civic_media/SURYA_INSTALL.md`.

**VLM routing:** All VLM calls go through Mission Control (`POST :8860/models/run`,
`model_id: "vision_model"`). MC routes to best available local model (llama3.2-vision:11b
or qwen2-vl:7b), with claude-haiku cloud fallback. Online/cloud tools seeding the DB
can use any vision-capable model — always set `model_id` to the full model name.

**Database:** `document_text` table — one row per page.
- `method`: `'pymupdf'` | `'surya'` | `'direct_read'` | `'vlm_description'`
- `model_id`: NULL for non-LLM rows; model name for VLM results (e.g., `'llama3.2-vision:11b'`)

**Full pipeline standard:** `E:\0-Automated-Apps\VISION_PIPELINE.md`

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

## Testing

No formal test suite exists yet. Use Playwright for browser-based UI testing and pytest for API/service tests.

### Setup

```bash
pip install playwright pytest httpx
python -m playwright install chromium
```

### Running Tests

```bash
pytest tests/ -v
pytest tests/ -v -k "browser"    # Playwright UI tests only
pytest tests/ -v -k "api"        # API tests only
```

### Writing Tests

- **Browser tests** go in `tests/test_browser.py` — use Playwright to verify the web UI (request list, search, document lightbox with preview/transcript, department filtering, stats dashboard)
- **API tests** go in `tests/test_api.py` — use httpx against FastAPI endpoints
- **Service tests** go in `tests/test_services.py` — unit tests for document processing, transcription client, PDF conversion
- The server must be running at localhost:8845 for browser tests

### Key Flows to Test

1. **Request browsing**: list loads, filters work, detail view shows timeline
2. **Document preview**: lightbox opens, PDF renders inline, Office docs show converted preview
3. **Transcription**: audio/video documents show transcript below player
4. **Search**: full-text search returns results across requests and documents
5. **Stats dashboard**: charts render with correct aggregate data

### Lazy ChromaDB Sync (Atlas RAG)
Atlas maintains a centralized ChromaDB vector store. This project does NOT need its
own vector DB. Atlas fetches candidate records from this spoke's search API, chunks
deterministically, validates against ChromaDB cache, and embeds only new/stale chunks.
ChromaDB is a cache — this spoke's SQLite DB is the source of truth.

See: `Atlas/app/services/rag/deterministic_chunking.py` for this spoke's chunking strategy.

## Master Schema & Codex References

**`E:\0-Automated-Apps\MASTER_SCHEMA.md`** — Canonical cross-project database
schema and API contracts. **HARD RULE: If you add, remove, or modify any database
tables, columns, API endpoints, or response shapes, you MUST update the Master
Schema before finishing your task.** Do not skip this — other projects read it to
understand this project's data contracts.

**`E:\0-Automated-Apps\MASTER_PROJECT.md`** describes the overall ecosystem
architecture and how all projects interconnect.

> **HARD RULE — READ AND UPDATE THE CODEX**
>
> **`E:\0-Automated-Apps\master_codex.md`** is the living interoperability codex.
> 1. **READ it** at the start of any session that touches APIs, schemas, tools,
>    chunking, person models, search, or integration with other projects.
> 2. **UPDATE it** before finishing any task that changes cross-project behavior.
>    This includes: new/changed API endpoints, database schema changes, new tools
>    or tool modifications in Atlas, chunking strategy changes, person model changes,
>    new cross-spoke dependencies, or completing items from a project's outstanding work list.
> 3. **DO NOT skip this.** The codex is how projects stay in sync. If you change
>    something that another project depends on and don't update the codex, the next
>    agent working on that project will build on stale assumptions and break things.


## AI Learning CODEX — Hard Rules

> **`E: -Automated-Apps\AI-Learning-CODEX\INDEX.md`** — shared technical knowledge base for all agents.
>
> **HARD RULE 1 — CHECK BEFORE STRUGGLING**
> At session start (if task touches Python compat, Blender, IPC, metaclasses, timers, or OS-specific code)
> OR after 2 failed attempts on the same problem:
> Scan the Quick-Find symptom table in `INDEX.md`. If your symptom matches, read the linked file
> before trying another approach. Takes under 60 seconds. May save hours.
>
> **HARD RULE 2 — CONTRIBUTE BEFORE CLOSING**
> If you solved a problem that required multiple interactions or non-obvious research:
> Add a dated entry to the relevant topic file, then update `INDEX.md` (symptom table + last-updated date).
> Never add to a topic file without also updating INDEX.md.
> See **`E:\0-Automated-Apps\MASTER_INDEX.md`** for fast navigation into both documents.
> See **`E:\0-Automated-Apps\NEW_APP_INTAKE.md`** before starting any new application.

## Unified Tools — Syllego (MMI)

If this project needs to download media from an external URL and doesn't have its own ingest path for that platform, **Syllego (MMI)** is available as an optional shared library.

```python
import os
os.environ["MMI_CALLER"] = "Shasta-PRA-Backup"   # identifies this app in Syllego's log
import mmi
result = mmi.ingest(url)   # returns IngestionResult
if result.success:
    print(result.filename)
```

**Install:** `pip install -e "E:/0-Automated-Apps/Unified-Tools/Syllego"`
**Supports:** YouTube, Facebook, Rumble, TikTok, Instagram, Reddit, Vimeo, and more.
**Full API:** `E:\0-Automated-Apps\Unified-Tools\Syllego\AGENT_SPEC.md`
