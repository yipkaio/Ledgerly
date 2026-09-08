"""Safe wrapper around the local Tesseract command-line application."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class OCRError(RuntimeError):
    """Base class for controlled OCR failures."""


class OCRUnavailableError(OCRError):
    """Raised when Tesseract cannot be started."""


class OCRTimeoutError(OCRError):
    """Raised when Tesseract exceeds its configured time limit."""


class OCRProcessingError(OCRError):
    """Raised when Tesseract cannot process an image."""


class OCRNoTextError(OCRError):
    """Raised when no readable text is detected."""


@dataclass(frozen=True)
class TesseractOCRService:
    executable: str
    language: str
    page_segmentation_mode: int
    timeout_seconds: int

    def extract_text(self, image_path: Path) -> str:
        command = [
            self.executable,
            str(image_path),
            "stdout",
            "-l",
            self.language,
            "--psm",
            str(self.page_segmentation_mode),
        ]

        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise OCRUnavailableError("Tesseract executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise OCRTimeoutError("Tesseract processing timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise OCRProcessingError("Tesseract could not process the image") from exc
        except OSError as exc:
            raise OCRUnavailableError("Tesseract could not be started") from exc

        text = completed.stdout.strip()
        if not text:
            raise OCRNoTextError("No readable receipt text was detected")
        return text
