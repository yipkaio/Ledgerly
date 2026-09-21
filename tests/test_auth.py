import asyncio

import httpx
from fastapi.testclient import TestClient
import pytest

from app.auth import FirebaseAuthError, verify_firebase_token
from app.config import ConfigurationError, Settings
from app.main import create_app

TEST_KEY = "test-key-that-is-longer-than-32-characters"


def configure_firebase(monkeypatch, mode: str = "hybrid") -> Settings:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-gateway-key")
    monkeypatch.setenv("AUTH_MODE", mode)
    monkeypatch.setenv("FIREBASE_WEB_API_KEY", "firebase-web-key-that-is-long-enough")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "ledgerly-demo")
    monkeypatch.setenv("FIREBASE_ALLOWED_UID", "bookkeeper-uid")
    monkeypatch.setenv("FIREBASE_ALLOWED_EMAIL", "bookkeeper@example.com")
    return Settings.from_environment()


def test_auth_config_defaults_to_api_key(monkeypatch) -> None:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-gateway-key")

    response = TestClient(create_app()).get("/auth/config")

    assert response.status_code == 200
    assert response.json() == {"mode": "api_key"}


def test_auth_config_exposes_only_public_firebase_values(monkeypatch) -> None:
    configure_firebase(monkeypatch)

    response = TestClient(create_app()).get("/auth/config")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "firebase",
        "firebase_web_api_key": "firebase-web-key-that-is-long-enough",
        "firebase_project_id": "ledgerly-demo",
    }
    assert TEST_KEY not in response.text


def test_hybrid_mode_keeps_trusted_integration_key(monkeypatch) -> None:
    configure_firebase(monkeypatch)

    response = TestClient(create_app()).get(
        "/receipts?limit=1", headers={"X-API-Key": TEST_KEY}
    )

    assert response.status_code == 200


def test_firebase_mode_rejects_the_integration_key(monkeypatch) -> None:
    configure_firebase(monkeypatch, mode="firebase")

    response = TestClient(create_app()).get(
        "/receipts?limit=1", headers={"X-API-Key": TEST_KEY}
    )

    assert response.status_code == 401


def test_allowed_firebase_bearer_token_is_accepted(monkeypatch) -> None:
    configure_firebase(monkeypatch, mode="firebase")

    async def allowed(token, settings):
        assert token == "valid-id-token"
        assert settings.firebase_allowed_uid == "bookkeeper-uid"

    monkeypatch.setattr("app.main.verify_firebase_token", allowed)
    response = TestClient(create_app()).get(
        "/receipts?limit=1",
        headers={"Authorization": "Bearer valid-id-token"},
    )

    assert response.status_code == 200


def test_firebase_verifier_rejects_another_account(monkeypatch) -> None:
    settings = configure_firebase(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "users": [
                    {
                        "localId": "another-user",
                        "email": "another@example.com",
                    }
                ]
            },
        )

    with pytest.raises(FirebaseAuthError):
        asyncio.run(
            verify_firebase_token(
                "unique-token-for-another-account",
                settings,
                transport=httpx.MockTransport(handler),
            )
        )


@pytest.mark.parametrize("value", ["unknown", "", "firebase-only"])
def test_invalid_auth_mode_is_rejected(monkeypatch, value: str) -> None:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-gateway-key")
    monkeypatch.setenv("AUTH_MODE", value)

    with pytest.raises(ConfigurationError):
        Settings.from_environment()


def test_firebase_mode_requires_an_allowed_uid(monkeypatch) -> None:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-gateway-key")
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_WEB_API_KEY", "firebase-web-key-that-is-long-enough")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "ledgerly-demo")
    monkeypatch.delenv("FIREBASE_ALLOWED_UID", raising=False)

    with pytest.raises(ConfigurationError):
        Settings.from_environment()
