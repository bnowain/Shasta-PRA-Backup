"""Configuration — paths, port, constants."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "shasta_nextrequest_backup"
DB_PATH = DATA_DIR / "nextrequest.db"
DOCS_DIR = DATA_DIR / "documents"
DATABASE_URL = f"sqlite:///{DB_PATH}"

PORT = 8845
