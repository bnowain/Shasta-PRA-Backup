"""Shasta PRA Backup — FastAPI application."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR
from app.routers import requests, departments, search, stats, documents

app = FastAPI(
    title="Shasta PRA Backup",
    description="Browse and search Shasta County public records requests.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(requests.router)
app.include_router(departments.router)
app.include_router(search.router)
app.include_router(stats.router)
app.include_router(documents.router)

# ── Static files ──────────────────────────────────────────────────────────────
_static_dir = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Frontend page routes ─────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(_static_dir / "index.html"))


@app.get("/requests", include_in_schema=False)
def requests_page():
    return FileResponse(str(_static_dir / "requests.html"))


@app.get("/requests/{pretty_id}", include_in_schema=False)
def request_detail_page(pretty_id: str):
    return FileResponse(str(_static_dir / "request.html"))


@app.get("/departments", include_in_schema=False)
def departments_page():
    return FileResponse(str(_static_dir / "departments.html"))


@app.get("/departments/{dept_id}", include_in_schema=False)
def department_detail_page(dept_id: int):
    return FileResponse(str(_static_dir / "department.html"))


@app.get("/search", include_in_schema=False)
def search_page():
    return FileResponse(str(_static_dir / "search.html"))


@app.get("/analytics", include_in_schema=False)
def analytics_page():
    return FileResponse(str(_static_dir / "analytics.html"))


# ── Favicon ───────────────────────────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["system"])
def health():
    from sqlalchemy import text
    from app.database import engine
    with engine.connect() as conn:
        req_count = conn.execute(text("SELECT COUNT(*) FROM requests")).scalar()
        doc_count = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar()
        dept_count = conn.execute(text("SELECT COUNT(*) FROM departments")).scalar()
    return {
        "status": "ok",
        "requests": req_count,
        "documents": doc_count,
        "departments": dept_count,
    }
