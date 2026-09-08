import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.ocr import (
    OCRNoTextError,
    OCRProcessingError,
    OCRTimeoutError,
    OCRUnavailableError,
    TesseractOCRService,
)


def service() -> TesseractOCRService:
    return TesseractOCRService(
        executable=r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        language="eng",
        page_segmentation_mode=6,
        timeout_seconds=30,
    )


@patch("app.ocr.subprocess.run")
def test_extract_text_uses_safe_argument_list(mock_run: Mock) -> None:
    mock_run.return_value = subprocess.CompletedProcess([], 0, "  RECEIPT TEXT\n", "")
    image_path = Path(r"C:\receipts\name & command.jpg")

    result = service().extract_text(image_path)

    assert result == "RECEIPT TEXT"
    mock_run.assert_called_once_with(
        [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            str(image_path),
            "stdout",
            "-l",
            "eng",
            "--psm",
            "6",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        shell=False,
    )


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (FileNotFoundError(), OCRUnavailableError),
        (subprocess.TimeoutExpired("tesseract", 30), OCRTimeoutError),
        (subprocess.CalledProcessError(1, ["tesseract"]), OCRProcessingError),
    ],
)
@patch("app.ocr.subprocess.run")
def test_subprocess_failures_are_converted(
    mock_run: Mock, side_effect: Exception, expected_error: type[Exception]
) -> None:
    mock_run.side_effect = side_effect

    with pytest.raises(expected_error):
        service().extract_text(Path("receipt.jpg"))


@patch("app.ocr.subprocess.run")
def test_empty_ocr_output_is_rejected(mock_run: Mock) -> None:
    mock_run.return_value = subprocess.CompletedProcess([], 0, "  \n", "")

    with pytest.raises(OCRNoTextError):
        service().extract_text(Path("receipt.jpg"))
