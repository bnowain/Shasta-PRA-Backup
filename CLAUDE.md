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
| GET | `/api/documents/{id}/file` | Serve downloaded document file |

## Database

SQLite at `shasta_nextrequest_backup/nextrequest.db`. Tables: `requests`, `timeline_events`, `documents`, `departments`, `scrape_log`. Schema created by `scraper.py` (raw sqlite3, not ORM). All API access is read-only via parameterized `text()` queries.

## Atlas Integration

Spoke key: `shasta_pra`. Registered in Atlas config on port 8845. Tools: `search_pra_requests`, `get_pra_request`, `list_pra_departments`, `get_pra_stats`, `search_pra_all`. RAG chunking uses metadata prefix + sliding window.

## Conventions

- Sync SQLAlchemy (not async) — matches civic_media pattern
- Raw `text()` queries, not ORM models — schema is externally created
- All API responses go through Pydantic schemas
- Frontend: each page has its own `.html` + `.js` pair, shared utilities in `app.js`
- Path traversal protection on document serving
- Dates in DB are `MM/DD/YYYY`, date range filtering rearranges with `substr()` for comparison
