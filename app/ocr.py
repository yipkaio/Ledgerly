"""Configurable, controlled OCR providers for receipt images."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Any, Protocol


class OCRError(RuntimeError):
    """Base class for controlled OCR failures."""


class OCRUnavailableError(OCRError):
    """Raised when the configured OCR provider cannot be started."""


class OCRTimeoutError(OCRError):
    """Raised when Tesseract exceeds its configured time limit."""


class OCRProcessingError(OCRError):
    """Raised when the configured OCR provider cannot process an image."""


class OCRNoTextError(OCRError):
    """Raised when no readable text is detected."""


@dataclass(frozen=True)
class OCRResult:
    """Provider-neutral OCR output for downstream receipt extraction."""

    text: str
    engine: str
    confidence: float | None = None


class OCRService(Protocol):
    """Contract implemented by every OCR provider."""

    def extract(self, image_path: Path) -> OCRResult:
        """Extract readable text from one validated image."""


@dataclass(frozen=True)
class TesseractOCRService:
    executable: str
    language: str
    page_segmentation_mode: int
    timeout_seconds: int

    def extract(self, image_path: Path) -> OCRResult:
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
        return OCRResult(text=text, engine="tesseract")


class PaddleOCRService:
    """In-process PaddleOCR provider with serialized access to one model."""

    def __init__(self, pipeline: Any, minimum_confidence: float) -> None:
        self._pipeline = pipeline
        self._minimum_confidence = minimum_confidence
        self._inference_lock = Lock()

    @classmethod
    def create(
        cls,
        language: str,
        device: str,
        minimum_confidence: float,
    ) -> "PaddleOCRService":
        try:
            from paddleocr import PaddleOCR
        except (ImportError, OSError) as exc:
            raise OCRUnavailableError("PaddleOCR is not installed") from exc

        try:
            pipeline = PaddleOCR(
                lang=language,
                device=device,
                use_doc_orientation_classify=True,
                use_doc_unwarping=True,
                use_textline_orientation=True,
            )
        except Exception as exc:
            raise OCRUnavailableError("PaddleOCR could not be initialized") from exc

        return cls(pipeline=pipeline, minimum_confidence=minimum_confidence)

    def extract(self, image_path: Path) -> OCRResult:
        try:
            with self._inference_lock:
                results = self._pipeline.predict(str(image_path))
                return self._parse_results(results)
        except OCRError:
            raise
        except Exception as exc:
            raise OCRProcessingError("PaddleOCR could not process the image") from exc

    def _parse_results(self, results: Any) -> OCRResult:
        accepted_text: list[str] = []
        accepted_scores: list[float] = []

        try:
            for result in results:
                payload = result.json
                data = payload["res"]
                texts = data["rec_texts"]
                scores = data["rec_scores"]

                if len(texts) != len(scores):
                    raise ValueError("Mismatched PaddleOCR text and score counts")

                for raw_text, raw_score in zip(texts, scores, strict=True):
                    if not isinstance(raw_text, str):
                        raise TypeError("PaddleOCR text must be a string")
                    score = float(raw_score)
                    if not isfinite(score) or not 0.0 <= score <= 1.0:
                        raise ValueError("PaddleOCR score is invalid")

                    text = raw_text.strip()
                    if text and score >= self._minimum_confidence:
                        accepted_text.append(text)
                        accepted_scores.append(score)
        except OCRError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise OCRProcessingError("PaddleOCR returned an invalid result") from exc

        if not accepted_text:
            raise OCRNoTextError("No readable receipt text was detected")

        average_confidence = sum(accepted_scores) / len(accepted_scores)
        return OCRResult(
            text="\n".join(accepted_text),
            engine="paddle",
            confidence=average_confidence,
        )
