# Last Session — 2026-02-22

## Changes Made

### People Table (NEW)
- **app/database.py** — Added `CREATE TABLE IF NOT EXISTS` for `people` and `request_people` tables in `_ensure_tables()`. Added indexes on `request_people(request_pretty_id)` and `request_people(person_id)`.
- **app/routers/people.py** — NEW FILE. People CRUD router with 4 endpoints:
  - `GET /api/people` — List/search people with request counts
  - `GET /api/people/{person_id}` — Person detail with linked requests
  - `POST /api/people` — Create a person
  - `POST /api/people/link` — Link a person to a PRA request
- **app/main.py** — Registered the `people` router.

### ISO Date Conversion
- **app/schemas.py** — Added `_to_iso()` helper function and Pydantic `field_validator` decorators on `RequestSummary`, `RequestDetail`, and `DocumentOut` to convert `MM/DD/YYYY` dates from the database to `YYYY-MM-DD` (ISO 8601) in API responses.
  - Affected fields: `request_date`, `due_date`, `closed_date`, `upload_date`
  - Database values and SQL queries are unchanged — conversion happens at the Pydantic serialization layer.

### Cross-Spoke Exception Rules
- **CLAUDE.md** — Updated conventions section to note that API responses now return ISO dates. DB still stores MM/DD/YYYY internally.

## What to Test
1. Start the app: `python start.py`
2. Verify `/api/health` returns OK
3. Check that `/api/requests` returns dates in `YYYY-MM-DD` format (was `MM/DD/YYYY`)
4. Check that `/api/requests/{pretty_id}` returns ISO dates for request_date, due_date, closed_date
5. Test date range filtering still works: `/api/requests?date_from=2024-01-01&date_to=2024-12-31`
6. Test people endpoints: `GET /api/people`, `POST /api/people?canonical_name=Test+Person`
7. Verify frontend still displays dates correctly (now shows YYYY-MM-DD format)
