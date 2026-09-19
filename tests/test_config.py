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
    assert settings.pdf_max_pages == 3
    assert settings.pdf_timeout_seconds == 30
    assert settings.pdf_max_render_pixels == 30_000_000
    assert settings.statement_pdf_max_bytes == 10_485_760
    assert settings.statement_pdf_max_pages == 30
    assert settings.statement_pdf_timeout_seconds == 60
    assert settings.statement_pdf_max_render_pixels == 60_000_000
    assert settings.statement_llm_max_output_tokens == 4_000


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PDF_MAX_PAGES", "0"),
        ("PDF_MAX_PAGES", "11"),
        ("PDF_TIMEOUT_SECONDS", "0"),
        ("PDF_TIMEOUT_SECONDS", "121"),
        ("PDF_MAX_RENDER_PIXELS", "999999"),
        ("PDF_MAX_RENDER_PIXELS", "not-a-number"),
        ("STATEMENT_PDF_MAX_BYTES", "999999"),
        ("STATEMENT_PDF_MAX_PAGES", "101"),
        ("STATEMENT_PDF_TIMEOUT_SECONDS", "181"),
        ("STATEMENT_PDF_MAX_RENDER_PIXELS", "999999"),
    ],
)
def test_invalid_pdf_limits_are_rejected(monkeypatch, name: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, **{name: value})


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


@pytest.mark.parametrize("value", ["499", "8001", "not-a-number"])
def test_invalid_statement_gateway_output_limit_is_rejected(monkeypatch, value: str) -> None:
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, STATEMENT_LLM_MAX_OUTPUT_TOKENS=value)


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
