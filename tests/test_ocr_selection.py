from unittest.mock import Mock, patch

from app.config import Settings
from app.main import get_ocr_service, get_paddle_ocr_service
from app.ocr import TesseractOCRService

TEST_KEY = "test-key-that-is-longer-than-32-characters"


def settings(monkeypatch, engine: str) -> Settings:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("OCR_ENGINE", engine)
    return Settings.from_environment()


def test_tesseract_provider_can_be_selected(monkeypatch) -> None:
    service = get_ocr_service(settings(monkeypatch, "tesseract"))

    assert isinstance(service, TesseractOCRService)


@patch("app.main.PaddleOCRService.create")
def test_paddle_provider_is_cached_per_configuration(
    create_service: Mock, monkeypatch
) -> None:
    get_paddle_ocr_service.cache_clear()
    expected = Mock()
    create_service.return_value = expected

    try:
        configured = settings(monkeypatch, "paddle")
        first = get_ocr_service(configured)
        second = get_ocr_service(configured)

        assert first is expected
        assert second is expected
        create_service.assert_called_once_with(
            language="en",
            device="cpu",
            minimum_confidence=0.50,
        )
    finally:
        get_paddle_ocr_service.cache_clear()
