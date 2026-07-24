from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("COMMERCIALCORE_DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"

for directory in (DATA_DIR, UPLOAD_DIR, REPORT_DIR):
    directory.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("COMMERCIALCORE_DATABASE_URL", f"sqlite:///{DATA_DIR / 'commercialcore.db'}")
SECRET_KEY = os.getenv("COMMERCIALCORE_SECRET", "development-secret-change-me")
ENVIRONMENT = os.getenv("COMMERCIALCORE_ENV", "development")

ADMIN_USERNAME = os.getenv("COMMERCIALCORE_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("COMMERCIALCORE_ADMIN_PASSWORD", "admin123")
ADMIN_FULL_NAME = os.getenv("COMMERCIALCORE_ADMIN_FULL_NAME", "Administrator")
