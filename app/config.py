"""Environment-backed application configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

TESSERACT_LANGUAGE_PATTERN = re.compile(r"[A-Za-z]{3}(?:\+[A-Za-z]{3})*")
PADDLE_LANGUAGE_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
PADDLE_DEVICE_PATTERN = re.compile(r"(?:cpu|gpu(?::\d+)?)")
OCR_ENGINES = {"paddle", "tesseract"}


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is invalid."""


def api_docs_enabled() -> bool:
    value = os.getenv("API_DOCS_ENABLED", "true").strip().lower()
    if value not in {"true", "false"}:
        raise ConfigurationError("API_DOCS_ENABLED must be true or false")
    return value == "true"


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
    llm_gateway_url: str
    llm_gateway_api_key: str
    llm_model: str
    llm_timeout_seconds: int
    llm_max_output_tokens: int
    classification_confidence_threshold: float
    database_path: Path = Path("data/expenses.db")

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

        llm_gateway_url = os.getenv(
            "LLM_GATEWAY_URL", "https://api.softwaresystems.app"
        ).strip()
        parsed_gateway_url = urlsplit(llm_gateway_url)
        if (
            parsed_gateway_url.scheme != "https"
            or not parsed_gateway_url.hostname
            or parsed_gateway_url.username is not None
            or parsed_gateway_url.password is not None
            or parsed_gateway_url.path not in ("", "/")
            or parsed_gateway_url.query
            or parsed_gateway_url.fragment
        ):
            raise ConfigurationError("LLM_GATEWAY_URL must be a secure HTTPS URL")

        llm_gateway_api_key = os.getenv("LLM_GATEWAY_API_KEY", "").strip()
        if not llm_gateway_api_key:
            raise ConfigurationError("LLM_GATEWAY_API_KEY must not be empty")

        llm_model = os.getenv(
            "LLM_MODEL", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
        ).strip()
        if not llm_model or len(llm_model) > 200:
            raise ConfigurationError("LLM_MODEL must contain 1 to 200 characters")

        llm_timeout_seconds = cls._bounded_integer(
            "LLM_TIMEOUT_SECONDS", "120", 1, 300
        )
        llm_max_output_tokens = cls._bounded_integer(
            "LLM_MAX_OUTPUT_TOKENS", "800", 100, 4000
        )
        classification_confidence_threshold = cls._bounded_float(
            "CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.80", 0.0, 1.0
        )

        database_path = os.getenv("DATABASE_PATH", "data/expenses.db").strip()
        if not database_path or "\x00" in database_path or database_path == ":memory:":
            raise ConfigurationError("DATABASE_PATH must be a persistent file path")

        upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
        return cls(
            app_api_key=api_key,
            upload_dir=upload_dir,
            database_path=Path(database_path),
            max_upload_bytes=max_upload_bytes,
            ocr_engine=ocr_engine,
            paddle_language=paddle_language,
            paddle_device=paddle_device,
            paddle_min_confidence=paddle_min_confidence,
            tesseract_cmd=tesseract_cmd,
            tesseract_language=language,
            tesseract_psm=tesseract_psm,
            ocr_timeout_seconds=ocr_timeout_seconds,
            llm_gateway_url=llm_gateway_url,
            llm_gateway_api_key=llm_gateway_api_key,
            llm_model=llm_model,
            llm_timeout_seconds=llm_timeout_seconds,
            llm_max_output_tokens=llm_max_output_tokens,
            classification_confidence_threshold=(
                classification_confidence_threshold
            ),
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
