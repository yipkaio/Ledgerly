from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app, get_ocr_service
from app.ocr import OCRResult, OCRTimeoutError

TEST_KEY = "test-key-that-is-longer-than-32-characters"


class StubOCRService:
    def __init__(self, text: str = "MR DIY\nTOTAL RM 33.90") -> None:
        self.text = text
        self.paths: list[Path] = []

    def extract(self, image_path: Path) -> OCRResult:
        self.paths.append(image_path)
        return OCRResult(text=self.text, engine="stub", confidence=0.95)


def configured_client(
    monkeypatch, tmp_path: Path, max_bytes: int = 1024
) -> tuple[TestClient, StubOCRService]:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(max_bytes))
    app = create_app()
    ocr_service = StubOCRService()
    app.dependency_overrides[get_ocr_service] = lambda: ocr_service
    return TestClient(app), ocr_service


def test_health_is_public() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_requires_authentication(monkeypatch, tmp_path: Path) -> None:
    client, _ = configured_client(monkeypatch, tmp_path)

    response = client.post(
        "/receipts/upload",
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == 401
    assert list(tmp_path.iterdir()) == []


def test_valid_jpeg_is_saved_with_generated_name(monkeypatch, tmp_path: Path) -> None:
    client, ocr_service = configured_client(monkeypatch, tmp_path)
    image = b"\xff\xd8\xffreceipt-data"

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("../../unsafe.jpg", image, "image/jpeg")},
    )

    assert response.status_code == 202
    payload = response.json()
    stored_files = list(tmp_path.iterdir())
    assert payload["status"] == "ocr_complete"
    assert payload["size_bytes"] == len(image)
    assert payload["ocr_engine"] == "stub"
    assert payload["ocr_confidence"] == 0.95
    assert payload["ocr_text"] == "MR DIY\nTOTAL RM 33.90"
    assert len(stored_files) == 1
    assert stored_files[0].name == f"{payload['receipt_id']}.jpg"
    assert stored_files[0].read_bytes() == image
    assert ocr_service.paths == [stored_files[0]]


def test_declared_type_must_match_file_signature(monkeypatch, tmp_path: Path) -> None:
    client, _ = configured_client(monkeypatch, tmp_path)

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"not-an-image", "image/jpeg")},
    )

    assert response.status_code == 415
    assert list(tmp_path.iterdir()) == []


def test_oversized_upload_is_rejected_and_removed(monkeypatch, tmp_path: Path) -> None:
    client, _ = configured_client(monkeypatch, tmp_path, max_bytes=5)

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xfftoo-large", "image/jpeg")},
    )

    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_ocr_failure_returns_safe_error_and_removes_upload(
    monkeypatch, tmp_path: Path
) -> None:
    client, ocr_service = configured_client(monkeypatch, tmp_path)

    def time_out(_: Path) -> str:
        raise OCRTimeoutError("internal timeout information")

    ocr_service.extract = time_out
    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == 504
    assert response.json() == {"detail": "Receipt OCR timed out"}
    assert list(tmp_path.iterdir()) == []
