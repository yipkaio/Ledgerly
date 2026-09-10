import pytest

from app.config import ConfigurationError, Settings

TEST_KEY = "test-key-that-is-longer-than-32-characters"


def configured_settings(monkeypatch, **values: str) -> Settings:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-gateway-key")
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


@pytest.mark.parametrize(
    "value",
    [
        "http://api.example.test",
        "https://user:password@example.test",
        "https://example.test?secret=value",
        "https://example.test/custom/path",
        "not-a-url",
    ],
)
def test_insecure_or_malformed_gateway_url_is_rejected(
    monkeypatch, value: str
) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, LLM_GATEWAY_URL=value)


def test_empty_gateway_key_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "")

    with pytest.raises(ConfigurationError):
        Settings.from_environment()


@pytest.mark.parametrize("value", ["99", "4001", "not-a-number"])
def test_invalid_gateway_output_limit_is_rejected(monkeypatch, value: str) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, LLM_MAX_OUTPUT_TOKENS=value)


def test_classification_confidence_threshold_defaults_to_eighty_percent(
    monkeypatch,
) -> None:
    settings = configured_settings(monkeypatch)

    assert settings.classification_confidence_threshold == 0.80


@pytest.mark.parametrize("value", ["-0.01", "1.01", "not-a-number", "nan"])
def test_invalid_classification_confidence_threshold_is_rejected(
    monkeypatch,
    value: str,
) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(
            monkeypatch,
            CLASSIFICATION_CONFIDENCE_THRESHOLD=value,
        )
