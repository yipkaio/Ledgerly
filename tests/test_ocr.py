import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.ocr import (
    OCRNoTextError,
    OCRProcessingError,
    OCRTimeoutError,
    OCRUnavailableError,
    PaddleOCRService,
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

    result = service().extract(image_path)

    assert result.text == "RECEIPT TEXT"
    assert result.engine == "tesseract"
    assert result.confidence is None
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
        service().extract(Path("receipt.jpg"))


@patch("app.ocr.subprocess.run")
def test_empty_ocr_output_is_rejected(mock_run: Mock) -> None:
    mock_run.return_value = subprocess.CompletedProcess([], 0, "  \n", "")

    with pytest.raises(OCRNoTextError):
        service().extract(Path("receipt.jpg"))


class FakePaddleResult:
    def __init__(self, texts, scores) -> None:
        self.json = {"res": {"rec_texts": texts, "rec_scores": scores}}


class FakePaddlePipeline:
    def __init__(self, results) -> None:
        self.results = results
        self.inputs: list[str] = []

    def predict(self, image_path: str):
        self.inputs.append(image_path)
        return self.results


def test_paddle_extracts_text_and_average_confidence() -> None:
    pipeline = FakePaddlePipeline(
        [FakePaddleResult([" Vendor ", "noise", "TOTAL 33.90"], [0.90, 0.20, 0.80])]
    )
    paddle = PaddleOCRService(pipeline=pipeline, minimum_confidence=0.50)

    result = paddle.extract(Path("receipt.jpg"))

    assert result.text == "Vendor\nTOTAL 33.90"
    assert result.engine == "paddle"
    assert result.confidence == pytest.approx(0.85)
    assert pipeline.inputs == ["receipt.jpg"]


def test_paddle_combines_multiple_result_pages() -> None:
    pipeline = FakePaddlePipeline(
        [
            FakePaddleResult(["PAGE ONE"], [0.91]),
            FakePaddleResult(["PAGE TWO"], [0.93]),
        ]
    )
    paddle = PaddleOCRService(pipeline=pipeline, minimum_confidence=0.50)

    result = paddle.extract(Path("receipt.png"))

    assert result.text == "PAGE ONE\nPAGE TWO"
    assert result.confidence == pytest.approx(0.92)


@pytest.mark.parametrize(
    "results",
    [
        [FakePaddleResult(["too uncertain"], [0.10])],
        [FakePaddleResult(["   "], [0.99])],
    ],
)
def test_paddle_rejects_results_without_accepted_text(results) -> None:
    paddle = PaddleOCRService(
        pipeline=FakePaddlePipeline(results), minimum_confidence=0.50
    )

    with pytest.raises(OCRNoTextError):
        paddle.extract(Path("receipt.jpg"))


@pytest.mark.parametrize(
    "result",
    [
        FakePaddleResult(["one"], []),
        FakePaddleResult(["one"], [1.5]),
    ],
)
def test_paddle_rejects_malformed_provider_results(result) -> None:
    paddle = PaddleOCRService(
        pipeline=FakePaddlePipeline([result]), minimum_confidence=0.50
    )

    with pytest.raises(OCRProcessingError):
        paddle.extract(Path("receipt.jpg"))


def test_paddle_converts_provider_failure_to_controlled_error() -> None:
    pipeline = Mock()
    pipeline.predict.side_effect = RuntimeError("internal model details")
    paddle = PaddleOCRService(pipeline=pipeline, minimum_confidence=0.50)

    with pytest.raises(OCRProcessingError) as captured:
        paddle.extract(Path("receipt.jpg"))

    assert str(captured.value) == "PaddleOCR could not process the image"
