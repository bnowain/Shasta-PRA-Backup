"""Sync SQLAlchemy engine and FastAPI dependency."""

from sqlalchemy import create_engine, event, text

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def _ensure_tables():
    """Create document_text and processing_log tables if they don't exist."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS document_text (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL DEFAULT 0,
                text_content TEXT NOT NULL,
                method TEXT NOT NULL,
                segments_json TEXT,
                duration_seconds REAL,
                processing_seconds REAL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (document_id) REFERENCES documents(id),
                UNIQUE(document_id, page_number, method)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS processing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL UNIQUE,
                aliases TEXT,
                role TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS request_people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_pretty_id TEXT NOT NULL,
                person_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (request_pretty_id) REFERENCES requests(pretty_id),
                FOREIGN KEY (person_id) REFERENCES people(id),
                UNIQUE(request_pretty_id, person_id, role)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_request_people_request
            ON request_people(request_pretty_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_request_people_person
            ON request_people(person_id)
        """))
        # Backfill file_size_mb from actual file_size_bytes where missing/zero
        conn.execute(text("""
            UPDATE documents SET file_size_mb = ROUND(file_size_bytes / (1024.0 * 1024.0), 2)
            WHERE file_size_bytes > 0 AND (file_size_mb IS NULL OR file_size_mb = 0)
        """))
        conn.commit()


_ensure_tables()


def get_db():
    """FastAPI dependency — yields a raw connection."""
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()
