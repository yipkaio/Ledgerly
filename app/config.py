"""Environment-backed application configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

TESSERACT_LANGUAGE_PATTERN = re.compile(r"[A-Za-z]{3}(?:\+[A-Za-z]{3})*")
PADDLE_LANGUAGE_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
PADDLE_DEVICE_PATTERN = re.compile(r"(?:cpu|gpu(?::\d+)?)")
OCR_ENGINES = {"paddle", "tesseract"}


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    app_api_key: str
    upload_dir: Path
    max_upload_bytes: int
    ocr_engine: str
    paddle_language: str
    paddle_device: str
    paddle_min_confidence: float
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

        ocr_engine = os.getenv("OCR_ENGINE", "paddle").strip().lower()
        if ocr_engine not in OCR_ENGINES:
            raise ConfigurationError("OCR_ENGINE must be paddle or tesseract")

        paddle_language = os.getenv("PADDLE_LANGUAGE", "en").strip()
        if PADDLE_LANGUAGE_PATTERN.fullmatch(paddle_language) is None:
            raise ConfigurationError("PADDLE_LANGUAGE has an invalid format")

        paddle_device = os.getenv("PADDLE_DEVICE", "cpu").strip().lower()
        if PADDLE_DEVICE_PATTERN.fullmatch(paddle_device) is None:
            raise ConfigurationError("PADDLE_DEVICE must be cpu, gpu, or gpu:<index>")

        paddle_min_confidence = cls._bounded_float(
            "PADDLE_MIN_CONFIDENCE", "0.50", 0.0, 1.0
        )

        tesseract_cmd = os.getenv("TESSERACT_CMD", "tesseract").strip()
        if not tesseract_cmd:
            raise ConfigurationError("TESSERACT_CMD must not be empty")

        language = os.getenv("TESSERACT_LANGUAGE", "eng").strip()
        if TESSERACT_LANGUAGE_PATTERN.fullmatch(language) is None:
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
            ocr_engine=ocr_engine,
            paddle_language=paddle_language,
            paddle_device=paddle_device,
            paddle_min_confidence=paddle_min_confidence,
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

    @staticmethod
    def _bounded_float(name: str, default: str, minimum: float, maximum: float) -> float:
        raw_value = os.getenv(name, default)
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ConfigurationError(f"{name} must be a number") from exc
        if not minimum <= value <= maximum:
            raise ConfigurationError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return value
