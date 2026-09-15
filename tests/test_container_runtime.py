"""Real installed OCR/runtime checks, enabled only in the Docker test target."""

import io
import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app, get_ocr_service
from app.ocr import TesseractOCRService
from test_api import TEST_KEY, configured_client

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CONTAINER_TESTS") != "1", reason="Requires the Docker test image"
)


def test_container_user_and_paddle_native_runtime():
    assert os.getuid() == 10001
    import paddle
    from paddleocr import PaddleOCR
    assert PaddleOCR is not None
    result = paddle.to_tensor([1.0, 2.0]) + 1
    assert result.numpy().tolist() == [2.0, 3.0]


def test_document_and_export_runtime_dependencies():
    import PIL
    import pypdf
    import pypdfium2
    import xlsxwriter

    assert PIL and pypdf and pypdfium2 and xlsxwriter


def test_real_tesseract_upload_and_saved_result(monkeypatch, tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    draw.multiline_text((40, 40), "SPOTIFY\nTOTAL 33.90\nTHANK YOU", fill="black", font=font, spacing=20)
    data = io.BytesIO()
    image.save(data, format="PNG")
    client, _, extractor, classifier = configured_client(monkeypatch, tmp_path, max_bytes=5242880)
    extractor.vendor = "SPOTIFY"
    client.app.dependency_overrides[get_ocr_service] = lambda: TesseractOCRService(
        executable="/usr/bin/tesseract", language="eng", page_segmentation_mode=6, timeout_seconds=30
    )
    response = client.post(
        "/receipts/upload", headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.png", data.getvalue(), "image/png")},
    )
    assert response.status_code == 202, response.text
    assert "SPOTIFY" in response.json()["ocr_text"]
    assert "33.90" in extractor.inputs[0]
    assert classifier.inputs == []
    receipt_id = response.json()["receipt_id"]
    saved = TestClient(create_app()).get(f"/receipts/{receipt_id}", headers={"X-API-Key": TEST_KEY})
    assert saved.json()["processing_status"] == "COMPLETED"
    assert saved.json()["ocr_engine"] == "tesseract"
