"""Configuration — paths, port, constants."""

import shutil
from pathlib import Path

import os

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_ROOT = Path(os.environ.get("PRA_STORAGE_ROOT", str(BASE_DIR))).resolve()
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
CONVERTIBLE_EXTENSIONS = {"docx", "doc", "pptx", "ppt", "odt", "ods", "odp", "rtf"}

# Text extraction
TEXT_EXTRACTABLE_EXTENSIONS = {"pdf"}
DIRECT_READ_EXTENSIONS = {"txt", "csv"}
IMAGE_OCR_EXTENSIONS = {"jpg", "jpeg", "png", "tif", "tiff", "bmp"}
OCR_MAX_FILE_SIZE_MB = 200

# Surya OCR — runs via civic_media's Python venv (GPU PyTorch, RTX 5090, cu128 build)
# Invoked as a subprocess to avoid Python 3.13 / 3.11 ABI incompatibility.
# See civic_media/SURYA_INSTALL.md for install notes and rollback instructions.
_CIVIC_MEDIA_PYTHON_CANDIDATES = [
    Path("E:/0-Automated-Apps/civic_media/venv/Scripts/python.exe"),
    Path("/mnt/e/0-Automated-Apps/civic_media/venv/Scripts/python.exe"),
    Path("/mnt/e/0-Automated-Apps/civic_media/venv/bin/python"),
]
CIVIC_MEDIA_PYTHON = next(
    (str(p) for p in _CIVIC_MEDIA_PYTHON_CANDIDATES if p.exists()), None
)
SURYA_WORKER = str(BASE_DIR / "scripts" / "surya_worker.py")
# Pages with fewer than this many chars are treated as scanned and sent to Surya
SURYA_MIN_CHARS_PER_PAGE = 50
