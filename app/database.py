"""Sync SQLAlchemy engine and FastAPI dependency."""

from sqlalchemy import create_engine, event

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


def get_db():
    """FastAPI dependency — yields a raw connection."""
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()
