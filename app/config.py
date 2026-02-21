"""Configuration — paths, port, constants."""

import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "shasta_nextrequest_backup"
DB_PATH = DATA_DIR / "nextrequest.db"
DOCS_DIR = DATA_DIR / "documents"
DATABASE_URL = f"sqlite:///{DB_PATH}"

PORT = 8845

# LibreOffice headless conversion for document preview
SOFFICE_PATH = shutil.which("soffice") or "soffice"
CONVERTIBLE_EXTENSIONS = {"docx", "doc", "xlsx", "xls", "pptx", "ppt", "odt", "ods", "odp", "rtf"}
