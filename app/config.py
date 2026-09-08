"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    app_api_key: str
    upload_dir: Path
    max_upload_bytes: int

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

        upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
        return cls(
            app_api_key=api_key,
            upload_dir=upload_dir,
            max_upload_bytes=max_upload_bytes,
        )
