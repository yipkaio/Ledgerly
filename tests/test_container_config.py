from fastapi.testclient import TestClient
import pytest

from app import container
from app.config import ConfigurationError, api_docs_enabled
from app.database import ReceiptStore
from app.main import create_app
from app.main import get_ocr_service
from app.ocr import OCRUnavailableError
from test_api import configured_client, TEST_KEY


def test_docs_can_be_disabled_without_disabling_health(monkeypatch):
    monkeypatch.setenv("API_DOCS_ENABLED", "false")
    client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


def test_docs_enabled_by_default(monkeypatch):
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    assert TestClient(create_app()).get("/openapi.json").status_code == 200


def test_invalid_docs_setting(monkeypatch):
    monkeypatch.setenv("API_DOCS_ENABLED", "maybe")
    with pytest.raises(ConfigurationError):
        api_docs_enabled()


def test_container_startup_creates_usable_database(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", "x" * 32)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-only")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "expenses.db"))
    monkeypatch.setenv("OCR_ENGINE", "tesseract")
    monkeypatch.setattr(container.shutil, "which", lambda value: "/usr/bin/tesseract")
    monkeypatch.setattr(container.Path, "home", lambda: tmp_path / "home")
    container.check_startup()
    assert ReceiptStore(tmp_path / "expenses.db").list(None, None, 20, 0)["total"] == 0
    assert list((tmp_path / "uploads").iterdir()) == []


def test_startup_failure_does_not_expose_details(monkeypatch, capsys):
    def broken():
        raise ConfigurationError("private secret or path")
    monkeypatch.setattr(container, "check_startup", broken)
    monkeypatch.setattr(container.os, "umask", lambda value: None)
    assert container.main() == 1
    assert "private" not in capsys.readouterr().err


def test_paddle_initialization_error_is_controlled(monkeypatch, tmp_path):
    client, _, extractor, classifier = configured_client(monkeypatch, tmp_path)
    client.app.dependency_overrides.pop(get_ocr_service)
    monkeypatch.setenv("OCR_ENGINE", "paddle")
    def unavailable(*args):
        raise OCRUnavailableError("private installation path")
    monkeypatch.setattr("app.main.get_paddle_ocr_service", unavailable)
    response = client.post(
        "/receipts/upload", headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "OCR service is unavailable"}
    assert extractor.inputs == classifier.inputs == []
