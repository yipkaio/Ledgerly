from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

TEST_KEY = "test-key-that-is-longer-than-32-characters"


def configured_client(monkeypatch, tmp_path: Path, max_bytes: int = 1024) -> TestClient:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(max_bytes))
    return TestClient(create_app())


def test_health_is_public() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_requires_authentication(monkeypatch, tmp_path: Path) -> None:
    client = configured_client(monkeypatch, tmp_path)

    response = client.post(
        "/receipts/upload",
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == 401
    assert list(tmp_path.iterdir()) == []


def test_valid_jpeg_is_saved_with_generated_name(monkeypatch, tmp_path: Path) -> None:
    client = configured_client(monkeypatch, tmp_path)
    image = b"\xff\xd8\xffreceipt-data"

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("../../unsafe.jpg", image, "image/jpeg")},
    )

    assert response.status_code == 202
    payload = response.json()
    stored_files = list(tmp_path.iterdir())
    assert payload["status"] == "uploaded"
    assert payload["size_bytes"] == len(image)
    assert len(stored_files) == 1
    assert stored_files[0].name == f"{payload['receipt_id']}.jpg"
    assert stored_files[0].read_bytes() == image


def test_declared_type_must_match_file_signature(monkeypatch, tmp_path: Path) -> None:
    client = configured_client(monkeypatch, tmp_path)

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"not-an-image", "image/jpeg")},
    )

    assert response.status_code == 415
    assert list(tmp_path.iterdir()) == []


def test_oversized_upload_is_rejected_and_removed(monkeypatch, tmp_path: Path) -> None:
    client = configured_client(monkeypatch, tmp_path, max_bytes=5)

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xfftoo-large", "image/jpeg")},
    )

    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []
