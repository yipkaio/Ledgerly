from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "integrations"
    / "openclaw"
    / "ledgerly-receipt"
    / "scripts"
    / "submit_receipt.py"
)
SPEC = importlib.util.spec_from_file_location("ledgerly_openclaw_bridge", SCRIPT)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_resolve_media_and_submit_returns_bounded_summary(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        receipt = root / "telegram-file.jpg"
        receipt.write_bytes(b"\xff\xd8\xff" + b"receipt")
        monkeypatch.setenv("LEDGERLY_ALLOWED_MEDIA_ROOTS", str(root))
        monkeypatch.setenv("LEDGERLY_API_KEY", "a" * 32)

        response = {
            "receipt_id": "d67ad919-1bec-4863-9d56-85af99d35d31",
            "ocr_text": "must never be returned",
            "extracted_data": {
                "vendor": "Example Shop",
                "legal_entity": None,
                "date": "2026-09-21",
                "currency": "SGD",
                "total_amount": 12.5,
            },
            "classification": {
                "category": "Office Supplies",
                "confidence": 0.91,
                "workflow_decision": "AUTO_FILED",
                "needs_review": False,
                "review_reasons": [],
            },
            "duplicate_candidates": [],
        }

        def fake_urlopen(request, timeout):
            assert request.full_url == "http://127.0.0.1:8000/receipts/upload"
            assert request.headers["X-api-key"] == "a" * 32
            assert timeout == 300
            return FakeResponse(json.dumps(response).encode())

        monkeypatch.setattr(bridge, "urlopen", fake_urlopen)
        result = bridge.submit(f"media://inbound/{receipt.name}", None)

    assert result["ok"] is True
    assert result["vendor"] == "Example Shop"
    assert result["status"] == "AUTO_FILED"
    assert "ocr_text" not in result


@pytest.mark.parametrize(
    "reference",
    ["https://example.com/receipt.jpg", "../receipt.jpg", "media://inbound/../receipt.jpg"],
)
def test_rejects_unmanaged_media_paths(monkeypatch, reference):
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv("LEDGERLY_ALLOWED_MEDIA_ROOTS", directory)
        with pytest.raises(bridge.BridgeError, match="OpenClaw-managed|invalid"):
            bridge._resolve_media(reference)


def test_rejects_symlink_even_inside_allowed_root(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original = root / "original.png"
        original.write_bytes(b"\x89PNG\r\n\x1a\nimage")
        link = root / "linked.png"
        try:
            link.symlink_to(original)
        except OSError:
            pytest.skip("symlinks are unavailable")
        monkeypatch.setenv("LEDGERLY_ALLOWED_MEDIA_ROOTS", str(root))
        with pytest.raises(bridge.BridgeError, match="unavailable"):
            bridge._resolve_media(str(link))


def test_rejects_extension_signature_mismatch(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fake.pdf"
        path.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-pdf")
        with pytest.raises(bridge.BridgeError, match="valid JPEG, PNG, or PDF"):
            bridge._inspect_file(path, 1024)


def test_api_url_is_loopback_only(monkeypatch):
    monkeypatch.setenv("LEDGERLY_API_URL", "https://ledgerly.example.com")
    with pytest.raises(bridge.BridgeError, match="loopback"):
        bridge._api_url()

