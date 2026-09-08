"""Environment-backed application configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

LANGUAGE_PATTERN = re.compile(r"[A-Za-z]{3}(?:\+[A-Za-z]{3})*")


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    app_api_key: str
    upload_dir: Path
    max_upload_bytes: int
    tesseract_cmd: str
    tesseract_language: str
    tesseract_psm: int
    ocr_timeout_seconds: int

    @classmethod
    def from_environment(cls) -> "Settings":
        api_key = os.getenv("APP_API_KEY", "")
        if len(api_key) < 32:
            raise ConfigurationError("APP_API_KEY must contain at least 32 characters")

        raw_limit = os.getenv("MAX_UPLOAD_BYTES", "5242880")
        try:
            max_upload_bytes = int(raw_limit)
        except ValueError as exc:
            raise ConfigurationError("MAX_UPLOAD_BYTES must be an integer") from exc
        if max_upload_bytes < 1:
            raise ConfigurationError("MAX_UPLOAD_BYTES must be positive")

        tesseract_cmd = os.getenv("TESSERACT_CMD", "tesseract").strip()
        if not tesseract_cmd:
            raise ConfigurationError("TESSERACT_CMD must not be empty")

        language = os.getenv("TESSERACT_LANGUAGE", "eng").strip()
        if LANGUAGE_PATTERN.fullmatch(language) is None:
            raise ConfigurationError("TESSERACT_LANGUAGE has an invalid format")

        tesseract_psm = cls._bounded_integer("TESSERACT_PSM", "6", 3, 13)
        ocr_timeout_seconds = cls._bounded_integer(
            "OCR_TIMEOUT_SECONDS", "30", 1, 300
        )

        upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
        return cls(
            app_api_key=api_key,
            upload_dir=upload_dir,
            max_upload_bytes=max_upload_bytes,
            tesseract_cmd=tesseract_cmd,
            tesseract_language=language,
            tesseract_psm=tesseract_psm,
            ocr_timeout_seconds=ocr_timeout_seconds,
        )

    @staticmethod
    def _bounded_integer(name: str, default: str, minimum: int, maximum: int) -> int:
        raw_value = os.getenv(name, default)
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ConfigurationError(f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise ConfigurationError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return value
