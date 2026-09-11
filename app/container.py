"""Container entry point: validate local configuration before serving traffic."""

import importlib.util
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryFile

import uvicorn

from app.config import ConfigurationError, Settings, api_docs_enabled
from app.database import DatabaseError, ReceiptStore


def check_startup() -> None:
    settings = Settings.from_environment()
    api_docs_enabled()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryFile(dir=settings.upload_dir):
        pass
    # Check actual cache home permissions without downloading models.
    cache = Path.home() / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    with TemporaryFile(dir=cache):
        pass
    if settings.ocr_engine == "tesseract":
        if shutil.which(settings.tesseract_cmd) is None:
            raise ConfigurationError("Tesseract executable is unavailable")
    elif importlib.util.find_spec("paddleocr") is None:
        raise ConfigurationError("PaddleOCR package is unavailable")
    with ReceiptStore(settings.database_path).connect() as db:
        # A rolled-back write verifies existing databases are writable too.
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE receipts SET updated_at=updated_at WHERE 0")
        db.rollback()


def main() -> int:
    os.umask(0o077)
    try:
        check_startup()
    except (ConfigurationError, DatabaseError, OSError):
        print("Startup checks failed. Check configuration, OCR installation and volume permissions.", file=sys.stderr)
        return 1
    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=8000, workers=1,
        proxy_headers=False, server_header=False, access_log=False,
        timeout_graceful_shutdown=300,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
