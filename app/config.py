"""Configuration — paths, port, constants."""

import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "shasta_nextrequest_backup"
DB_PATH = DATA_DIR / "nextrequest.db"
DOCS_DIR = DATA_DIR / "documents"
DATABASE_URL = f"sqlite:///{DB_PATH}"

PORT = 8845

# civic_media transcription service
CIVIC_MEDIA_URL = "http://127.0.0.1:8000"
TRANSCRIBE_ENDPOINT = f"{CIVIC_MEDIA_URL}/api/transcribe"
TRANSCRIBABLE_EXTENSIONS = {"mp4", "mkv", "mov", "avi", "webm",
                            "mp3", "m4a", "wav", "ogg", "flac"}
TRANSCRIBE_CONNECT_TIMEOUT = 3     # fast fail if civic_media is down
TRANSCRIBE_READ_TIMEOUT = 900      # 15 min for large files

# LibreOffice headless conversion for document preview
_SOFFICE_CANDIDATES = [
    BASE_DIR / "tools" / "LibreOffice" / "App" / "libreoffice" / "program" / "soffice.exe",
    Path("C:/Program Files/LibreOffice/program/soffice.exe"),
]
SOFFICE_PATH = next((str(p) for p in _SOFFICE_CANDIDATES if p.exists()), None) or shutil.which("soffice") or "soffice"
CONVERTIBLE_EXTENSIONS = {"docx", "doc", "xlsx", "xls", "pptx", "ppt", "odt", "ods", "odp", "rtf"}

# Text extraction (OCR Phase 1: native text only, no OCR)
TEXT_EXTRACTABLE_EXTENSIONS = {"pdf"}
DIRECT_READ_EXTENSIONS = {"txt", "csv"}
OCR_MAX_FILE_SIZE_MB = 200
