# Shasta County NextRequest Backup Scraper v2

Backs up all public records requests and documents from:  
**https://shastacountyca.nextrequest.com/requests/**

## How it works

The NextRequest portal is a Vue.js single-page app. By reverse-engineering the
frontend JavaScript bundle (`api-CsHJ4m8l.js`), we discovered the internal
`/client/*` JSON API endpoints that the app calls. These work without
authentication for public portals.

**No browser or Playwright needed** — this is pure Python HTTP requests, making
it fast and reliable.

### Key API endpoints discovered

| Endpoint | Purpose |
|---|---|
| `GET /client/requests` | Paginated request listings |
| `GET /client/requests/{id}` | Single request detail |
| `GET /client/requests/{id}/timeline` | Timeline events |
| `GET /client/request_documents` | Documents for a request |
| `GET /client/requests/{id}/folders` | Document folders |
| `GET /s3_url?document_id={id}` | Direct S3 download link |
| `GET /client/departments` | All departments |
| `GET /client/account` | Portal configuration |

## Quick Start

```bash
pip install -r requirements.txt
python scraper.py
```

## Usage

```bash
# Full scrape: metadata + document downloads
python scraper.py

# Metadata only (fast ~20 min first pass, no file downloads)
python scraper.py --no-docs

# Just the request listings (fastest, ~2 min)
python scraper.py --list-only

# Download documents for already-scraped requests
python scraper.py --docs-only

# Resume detail scraping from a specific request
python scraper.py --resume-from 26-100
```

## Output

```
shasta_nextrequest_backup/
├── nextrequest.db              # SQLite database (all metadata)
├── scrape_stats.json           # Summary stats
├── documents/                  # Downloaded files by request ID
│   ├── 26-309/
│   ├── 25-389/
│   │   ├── 1 News PRA.pdf
│   │   ├── 5 Sinner report cont._PRA Redacted.pdf
│   │   └── ... (557 documents)
│   └── ...
└── raw_responses/              # Raw JSON API responses
    ├── account.json
    ├── listing_p1.json
    └── ...
```

## Querying the Database

```sql
-- Count by status
SELECT status, COUNT(*) FROM requests GROUP BY status;

-- Search request text
SELECT pretty_id, substr(request_text, 1, 200) 
FROM requests WHERE request_text LIKE '%Sinner%';

-- Requests by department
SELECT departments, COUNT(*) FROM requests 
GROUP BY departments ORDER BY COUNT(*) DESC;

-- Requests with most documents
SELECT d.request_pretty_id, COUNT(*) as n
FROM documents d GROUP BY d.request_pretty_id ORDER BY n DESC LIMIT 20;

-- Undownloaded documents
SELECT request_pretty_id, filename FROM documents WHERE downloaded = 0;

-- Total download size
SELECT SUM(file_size) / 1048576.0 as total_mb 
FROM documents WHERE downloaded = 1;
```

## Rate Limiting

Default: 1 second between API calls, 0.75s between downloads. Adjust in the
Configuration section at the top of `scraper.py`. Checkpoints to SQLite every
50 requests so you can safely interrupt and resume.

## Notes

- ~1,306 requests as of February 2026
- The portal states: **"ALL REQUESTS ARE MADE PUBLIC"**
- Some requests (like 25-389, the Lora Sinner case) have hundreds of documents
- The scraper stores the complete raw JSON from every API response
