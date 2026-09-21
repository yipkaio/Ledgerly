"""Firebase authentication boundary for the single trusted workspace."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time

import httpx

from app.config import Settings

FIREBASE_LOOKUP_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:lookup"
)
MAX_ID_TOKEN_LENGTH = 4096
CACHE_SECONDS = 300


class FirebaseAuthError(RuntimeError):
    """Raised when a Firebase token is invalid or belongs to another account."""


class FirebaseAuthUnavailable(RuntimeError):
    """Raised when Firebase cannot be reached safely."""


@dataclass(frozen=True)
class FirebasePrincipal:
    uid: str
    email: str | None


_verification_cache: dict[str, tuple[float, FirebasePrincipal]] = {}


async def verify_firebase_token(
    token: str,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FirebasePrincipal:
    """Validate a Firebase ID token and enforce the configured bookkeeper UID."""

    if (
        not token
        or len(token) > MAX_ID_TOKEN_LENGTH
        or settings.firebase_web_api_key is None
        or settings.firebase_allowed_uid is None
    ):
        raise FirebaseAuthError("Invalid Firebase token")

    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cached = _verification_cache.get(fingerprint)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return cached[1]

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0),
            follow_redirects=False,
            transport=transport,
        ) as client:
            response = await client.post(
                FIREBASE_LOOKUP_URL,
                params={"key": settings.firebase_web_api_key},
                json={"idToken": token},
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise FirebaseAuthUnavailable("Firebase authentication is unavailable") from exc

    if response.status_code in {400, 401, 403}:
        raise FirebaseAuthError("Invalid Firebase token")
    if response.status_code != 200:
        raise FirebaseAuthUnavailable("Firebase authentication is unavailable")

    try:
        payload = response.json()
        users = payload["users"]
        user = users[0]
        uid = user["localId"]
        email = user.get("email")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise FirebaseAuthError("Invalid Firebase response") from exc

    if not isinstance(uid, str) or uid != settings.firebase_allowed_uid:
        raise FirebaseAuthError("Firebase account is not allowed")
    if email is not None and not isinstance(email, str):
        raise FirebaseAuthError("Invalid Firebase response")
    if (
        settings.firebase_allowed_email is not None
        and (email is None or email.casefold() != settings.firebase_allowed_email)
    ):
        raise FirebaseAuthError("Firebase account is not allowed")

    principal = FirebasePrincipal(uid=uid, email=email)
    _verification_cache[fingerprint] = (now + CACHE_SECONDS, principal)
    if len(_verification_cache) > 256:
        expired = [
            key for key, (expiry, _) in _verification_cache.items() if expiry <= now
        ]
        for key in expired:
            _verification_cache.pop(key, None)
    return principal
