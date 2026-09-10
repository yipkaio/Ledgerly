import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.database import ReceiptStore, DatabaseError
from app.extraction import ExtractionTimeoutError
from app.main import create_app
from app.ocr import OCRTimeoutError
from test_api import TEST_KEY, configured_client

HEADERS = {"X-API-Key": TEST_KEY}
FILES = {"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")}


def test_result_survives_new_application(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)
    extractor.vendor = "SPOTIFY"
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    assert response.status_code == 202
    original = response.json()
    restarted = TestClient(create_app())
    saved = restarted.get("/receipts/" + original["receipt_id"], headers=HEADERS)
    assert saved.status_code == 200
    assert saved.json()["classification"] == original["classification"]
    assert saved.json()["extracted_data"] == original["extracted_data"]
    assert saved.json()["processing_status"] == "COMPLETED"
    assert "image_path" not in saved.json()
    assert restarted.get("/receipts/" + original["receipt_id"]).status_code == 401


def test_review_filter_and_pagination(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)
    client.post("/receipts/upload", headers=HEADERS, files=FILES)
    extractor.needs_review = True
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    page = client.get("/receipts?decision=REVIEW_QUEUE", headers=HEADERS).json()
    assert page["total"] == 1
    assert page["items"][0]["receipt_id"] == response.json()["receipt_id"]
    assert page["items"][0]["processing_status"] == "REVIEW_QUEUE"
    page = client.get("/receipts?limit=1&offset=1", headers=HEADERS).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert client.get("/receipts", headers=HEADERS).json()["limit"] == 20
    assert client.get("/receipts").status_code == 401


@pytest.mark.parametrize("url", ["/receipts?limit=0", "/receipts?limit=101", "/receipts?offset=-1",
                                     "/receipts?decision=INVALID", "/receipts?processing_status=INVALID",
                                     "/receipts/not-a-uuid"])
def test_query_validation(monkeypatch, tmp_path, url):
    client, *_ = configured_client(monkeypatch, tmp_path)
    assert client.get(url, headers=HEADERS).status_code == 422


def test_missing_receipt(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    assert client.get(f"/receipts/{uuid4()}", headers=HEADERS).status_code == 404


def test_failed_extraction_is_retrievable(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)
    extractor.error = ExtractionTimeoutError("private key")
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    assert response.status_code == 504
    saved = client.get("/receipts/" + response.headers["X-Receipt-ID"], headers=HEADERS)
    assert saved.json()["processing_status"] == "FAILED"
    assert saved.json()["ocr_text"]
    assert "private key" not in saved.text


def test_database_failure_stops_paid_processing(monkeypatch, tmp_path):
    client, ocr, extractor, classifier = configured_client(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path))  # Directory, not a file.
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    assert response.status_code == 503
    assert response.json() == {"detail": "Receipt database is unavailable"}
    assert ocr.paths == extractor.inputs == classifier.inputs == []
    assert not list(tmp_path.iterdir())


def test_api_uses_database_vendor_mappings(monkeypatch, tmp_path):
    client, _, extractor, classifier = configured_client(monkeypatch, tmp_path)
    store = ReceiptStore(Path(os.environ["DATABASE_PATH"]))
    with store.connect() as db:
        db.execute("INSERT INTO vendor_category_mappings VALUES (?, ?)", ("TEST VENDOR", "Utilities"))
    extractor.vendor = "Test Vendor"
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    assert response.json()["classification"]["category"] == "Utilities"
    assert classifier.inputs == []


def test_completion_write_failure_is_not_success(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    def fail_write(self, payload):
        raise DatabaseError("private disk error")
    monkeypatch.setattr(ReceiptStore, "complete", fail_write)
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    assert response.status_code == 503
    assert "private" not in response.text


def test_unexpected_processing_failure_is_safe(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)
    extractor.error = RuntimeError("private details")
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    assert response.status_code == 500
    saved = client.get("/receipts/" + response.headers["X-Receipt-ID"], headers=HEADERS).json()
    assert saved["error"] == "Receipt processing failed"


def test_ocr_failure_record_survives_image_cleanup(monkeypatch, tmp_path):
    client, ocr, _, _ = configured_client(monkeypatch, tmp_path)
    def timeout(path):
        raise OCRTimeoutError("private OCR details")
    ocr.extract = timeout
    response = client.post("/receipts/upload", headers=HEADERS, files=FILES)
    assert response.status_code == 504
    result = client.get("/receipts/" + response.headers["X-Receipt-ID"], headers=HEADERS).json()
    assert result["processing_status"] == "FAILED"
    assert result["error"] == "Receipt OCR timed out"
    assert list(tmp_path.iterdir()) == []
