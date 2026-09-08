import pytest

from app.config import ConfigurationError, Settings

TEST_KEY = "test-key-that-is-longer-than-32-characters"


def configured_settings(monkeypatch, **values: str) -> Settings:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return Settings.from_environment()


def test_paddle_is_the_default_ocr_engine(monkeypatch) -> None:
    settings = configured_settings(monkeypatch)

    assert settings.ocr_engine == "paddle"
    assert settings.paddle_language == "en"
    assert settings.paddle_device == "cpu"
    assert settings.paddle_min_confidence == 0.50


@pytest.mark.parametrize("value", ["", "unknown", "paddle;command"])
def test_invalid_ocr_engine_is_rejected(monkeypatch, value: str) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, OCR_ENGINE=value)


@pytest.mark.parametrize("value", ["-0.1", "1.1", "not-a-number", "nan"])
def test_invalid_paddle_confidence_is_rejected(monkeypatch, value: str) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, PADDLE_MIN_CONFIDENCE=value)


@pytest.mark.parametrize("value", ["cpu;command", "gpu:-1", "unknown"])
def test_invalid_paddle_device_is_rejected(monkeypatch, value: str) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, PADDLE_DEVICE=value)
