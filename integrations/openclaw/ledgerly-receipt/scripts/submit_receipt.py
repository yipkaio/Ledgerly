#!/usr/bin/env python3
"""Bounded OpenClaw-to-Ledgerly receipt bridge.

The helper accepts only OpenClaw-managed inbound files, posts one file to the
existing Ledgerly pipeline, and prints a deliberately small JSON summary.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
MAX_RESPONSE_BYTES = 1_000_000
ALLOWED_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


class BridgeError(RuntimeError):
    """A safe, user-displayable bridge failure."""

    def __init__(self, message: str, *, receipt_id: str | None = None) -> None:
        super().__init__(message)
        self.receipt_id = receipt_id


def _api_url() -> str:
    raw = os.getenv("LEDGERLY_API_URL", DEFAULT_API_URL).strip().rstrip("/")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BridgeError("Ledgerly API URL must be a loopback HTTP origin")
    return raw


def _api_key() -> str:
    value = os.getenv("LEDGERLY_API_KEY", "")
    if len(value) < 32:
        raise BridgeError("Ledgerly integration key is not configured")
    return value


def _max_bytes() -> int:
    raw = os.getenv("LEDGERLY_MAX_RECEIPT_BYTES", str(DEFAULT_MAX_BYTES))
    try:
        value = int(raw)
    except ValueError as exc:
        raise BridgeError("Ledgerly receipt size limit is invalid") from exc
    if not 1 <= value <= 25 * 1024 * 1024:
        raise BridgeError("Ledgerly receipt size limit is invalid")
    return value


def _allowed_roots() -> list[Path]:
    configured = os.getenv("LEDGERLY_ALLOWED_MEDIA_ROOTS", "").strip()
    roots = (
        configured.split(os.pathsep)
        if configured
        else [
            "~/.openclaw/media/inbound",
            "~/.openclaw/workspace/media/inbound",
        ]
    )
    return [Path(value).expanduser().resolve() for value in roots if value]


def _resolve_media(reference: str) -> Path:
    if "\x00" in reference:
        raise BridgeError("Receipt attachment reference is invalid")
    if reference.startswith("media://inbound/"):
        relative = reference.removeprefix("media://inbound/")
        if not relative or Path(relative).is_absolute() or len(Path(relative).parts) != 1:
            raise BridgeError("Receipt attachment reference is invalid")
        candidates = [root / relative for root in _allowed_roots()]
    elif reference.startswith("media/inbound/"):
        relative = reference.removeprefix("media/inbound/")
        if not relative or Path(relative).is_absolute() or len(Path(relative).parts) != 1:
            raise BridgeError("Receipt attachment reference is invalid")
        candidates = [root / relative for root in _allowed_roots()]
    else:
        path = Path(reference).expanduser()
        if not path.is_absolute() or ".." in path.parts:
            raise BridgeError("Receipt attachment must be OpenClaw-managed media")
        candidates = [path]

    roots = _allowed_roots()
    for candidate in candidates:
        resolved = candidate.resolve()
        for root in roots:
            if not resolved.is_relative_to(root):
                continue
            try:
                unresolved_relative = candidate.absolute().relative_to(root)
            except ValueError:
                continue
            current = root
            contains_symlink = False
            for part in unresolved_relative.parts:
                current = current / part
                if current.is_symlink():
                    contains_symlink = True
                    break
            if resolved.is_file() and not contains_symlink:
                return resolved
    raise BridgeError("Receipt attachment is unavailable or outside OpenClaw media storage")


def _inspect_file(path: Path, max_bytes: int) -> tuple[bytes, str]:
    try:
        size = path.stat().st_size
        if not 1 <= size <= max_bytes:
            raise BridgeError("Receipt attachment is empty or exceeds the upload limit")
        content = path.read_bytes()
    except OSError as exc:
        raise BridgeError("Receipt attachment could not be read") from exc

    guessed, _ = mimetypes.guess_type(path.name)
    if guessed == "image/jpg":
        guessed = "image/jpeg"
    if guessed not in ALLOWED_TYPES or not any(
        content.startswith(signature) for signature in ALLOWED_TYPES[guessed]
    ):
        raise BridgeError("Receipt must be a valid JPEG, PNG, or PDF file")
    return content, guessed


def _multipart(content: bytes, content_type: str, purpose: str | None) -> tuple[bytes, str]:
    boundary = f"ledgerly-{uuid4().hex}"
    safe_filename = "receipt" + {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}[content_type]
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="receipt"; filename="{safe_filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        b"\r\n",
    ]
    if purpose:
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="business_purpose"\r\n\r\n',
                purpose.encode("utf-8"),
                b"\r\n",
            ]
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _read_json(response) -> dict:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise BridgeError("Ledgerly returned an oversized response")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise BridgeError("Ledgerly returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise BridgeError("Ledgerly returned an invalid response")
    return payload


def _safe_http_error(exc: HTTPError) -> BridgeError:
    receipt_id = exc.headers.get("X-Receipt-ID") if exc.headers else None
    message = {
        401: "Ledgerly rejected the integration key",
        409: "This receipt was already uploaded",
        413: "Receipt exceeds Ledgerly's upload limit",
        415: "Ledgerly rejected the receipt file type",
        422: "Ledgerly could not process this receipt",
        502: "Ledgerly received an invalid extraction response",
        503: "Ledgerly is temporarily unavailable",
        504: "Ledgerly processing timed out",
    }.get(exc.code, "Ledgerly could not accept the receipt")
    try:
        payload = _read_json(exc)
        existing = payload.get("existing_receipt_id")
        if exc.code == 409 and isinstance(existing, str):
            receipt_id = existing
    except BridgeError:
        pass
    return BridgeError(message, receipt_id=receipt_id)


def submit(reference: str, purpose: str | None) -> dict:
    normalized_purpose = purpose.strip() if purpose else None
    if normalized_purpose and len(normalized_purpose) > 500:
        raise BridgeError("Business purpose must be 500 characters or fewer")
    path = _resolve_media(reference)
    content, content_type = _inspect_file(path, _max_bytes())
    body, boundary = _multipart(content, content_type, normalized_purpose)
    request = Request(
        f"{_api_url()}/receipts/upload",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "X-API-Key": _api_key(),
            "User-Agent": "ledgerly-openclaw-bridge/1.0",
        },
    )
    try:
        with urlopen(request, timeout=300) as response:
            payload = _read_json(response)
    except HTTPError as exc:
        raise _safe_http_error(exc) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise BridgeError("Ledgerly is unreachable; check the local API service") from exc

    extracted = payload.get("extracted_data")
    classification = payload.get("classification")
    if not isinstance(extracted, dict) or not isinstance(classification, dict):
        raise BridgeError("Ledgerly returned an incomplete response")
    confidence = classification.get("confidence")
    raw_review_reasons = classification.get("review_reasons")
    review_reasons = (
        [reason for reason in raw_review_reasons if isinstance(reason, str)][:5]
        if isinstance(raw_review_reasons, list)
        else []
    )
    raw_duplicates = payload.get("duplicate_candidates")
    duplicate_count = len(raw_duplicates) if isinstance(raw_duplicates, list) else 0
    return {
        "ok": True,
        "receipt_id": payload.get("receipt_id"),
        "vendor": extracted.get("vendor") or extracted.get("legal_entity"),
        "date": extracted.get("date"),
        "currency": extracted.get("currency"),
        "total_amount": extracted.get("total_amount"),
        "category": classification.get("category"),
        "confidence": confidence if isinstance(confidence, (int, float)) else None,
        "status": classification.get("workflow_decision"),
        "needs_review": bool(classification.get("needs_review")),
        "review_reasons": review_reasons,
        "duplicate_count": duplicate_count,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit OpenClaw inbound media to Ledgerly")
    parser.add_argument("--file", required=True, help="OpenClaw-managed inbound media reference")
    parser.add_argument("--business-purpose", help="Explicit user-provided purpose, up to 500 characters")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = submit(args.file, args.business_purpose)
    except BridgeError as exc:
        result = {"ok": False, "message": str(exc)}
        if exc.receipt_id:
            result["receipt_id"] = exc.receipt_id
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
