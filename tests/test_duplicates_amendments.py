import copy
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.database import DatabaseError, ReceiptStore
from test_api import TEST_KEY, configured_client


HEADERS = {"X-API-Key": TEST_KEY}


def upload(client, content=b"\xff\xd8\xffsame-receipt"):
    return client.post(
        "/receipts/upload",
        headers=HEADERS,
        files={"receipt": ("receipt.jpg", content, "image/jpeg")},
    )


def amendment_body(receipt, **changes):
    data = copy.deepcopy(receipt["extracted_data"])
    data.update(changes)
    return {
        "request_id": str(uuid4()),
        "expected_version": receipt.get("record_version", 0),
        "reviewer": "Yip Kai",
        "reason": "Corrected the receipt after checking the retained original image",
        "evidence_confirmed": True,
        "final_data": data,
        "category": "Office Supplies",
    }


def test_exact_duplicate_stops_before_ocr_and_returns_existing_id(monkeypatch, tmp_path):
    client, ocr, extractor, classifier = configured_client(monkeypatch, tmp_path)
    first = upload(client)
    assert first.status_code == 202
    calls = (len(ocr.paths), len(extractor.inputs), len(classifier.inputs))

    duplicate = upload(client)

    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "detail": "This exact receipt file was already uploaded",
        "existing_receipt_id": first.json()["receipt_id"],
    }
    assert duplicate.headers["X-Receipt-ID"] == first.json()["receipt_id"]
    assert (len(ocr.paths), len(extractor.inputs), len(classifier.inputs)) == calls
    assert len(list(tmp_path.glob("*.jpg"))) == 1


def test_different_file_is_not_blocked_by_vendor_and_amount(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    assert upload(client, b"\xff\xd8\xffone").status_code == 202
    assert upload(client, b"\xff\xd8\xfftwo").status_code == 202


def test_strict_post_extraction_match_is_sent_to_review(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)
    original_extract = extractor.extract

    async def with_receipt_number(text):
        result = await original_extract(text)
        return result.model_copy(update={"receipt_number": "R-100"})

    extractor.extract = with_receipt_number
    first = upload(client, b"\xff\xd8\xffphoto-one").json()
    second_response = upload(client, b"\xff\xd8\xffrecompressed-photo")
    assert second_response.status_code == 202
    second = second_response.json()
    assert second["duplicate_candidates"] == [first["receipt_id"]]
    assert second["classification"]["workflow_decision"] == "REVIEW_QUEUE"
    assert any("Possible duplicate" in reason for reason in second["classification"]["review_reasons"])
    saved = client.get(f"/receipts/{second['receipt_id']}", headers=HEADERS).json()
    assert saved["duplicate_candidates"] == [first["receipt_id"]]


def test_auto_filed_receipt_can_be_amended_without_overwriting_evidence(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    original = upload(client).json()
    rid = original["receipt_id"]
    saved = client.get(f"/receipts/{rid}", headers=HEADERS).json()
    body = amendment_body(saved, vendor="Verified vendor", total_amount=34.00,
                          subtotal=34.00, total_before_rounding=34.00,
                          rounding_adjustment=0.00, change_amount=16.00)

    response = client.post(f"/receipts/{rid}/amendments", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["record_version"] == 1
    assert result["final_data"]["vendor"] == "Verified vendor"

    detail = client.get(f"/receipts/{rid}", headers=HEADERS).json()
    assert detail["extracted_data"] == original["extracted_data"]
    assert detail["effective_data"]["vendor"] == "Verified vendor"
    assert detail["amendment"] == result
    assert detail["record_version"] == 1
    row = client.get("/receipts", headers=HEADERS).json()["items"][0]
    assert row["vendor"] == "Verified vendor"
    assert row["review_decision"] == "AMENDED"
    assert client.post(f"/receipts/{rid}/amendments", headers=HEADERS, json=body).json() == result

    events = client.get(f"/receipts/{rid}/amendments", headers=HEADERS).json()["items"]
    assert events[0]["before"]["final_data"] == original["extracted_data"]
    assert events[0]["before"]["state"] == "AUTO_FILED"


def test_amendments_are_versioned_and_stale_writes_fail(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    original = upload(client).json()
    rid = original["receipt_id"]
    first = amendment_body(original, vendor="First verified vendor")
    assert client.post(f"/receipts/{rid}/amendments", headers=HEADERS, json=first).status_code == 200

    stale = amendment_body(original, vendor="Stale edit")
    assert client.post(f"/receipts/{rid}/amendments", headers=HEADERS, json=stale).status_code == 409
    current = client.get(f"/receipts/{rid}", headers=HEADERS).json()
    second = amendment_body(current, vendor="Second verified vendor")
    second["expected_version"] = 1
    assert client.post(f"/receipts/{rid}/amendments", headers=HEADERS, json=second).json()["record_version"] == 2
    assert len(client.get(f"/receipts/{rid}/amendments", headers=HEADERS).json()["items"]) == 2


def test_amendment_routes_require_auth_and_audit_is_immutable(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    original = upload(client).json()
    rid = original["receipt_id"]
    body = amendment_body(original)
    assert client.post(f"/receipts/{rid}/amendments", json=body).status_code == 401
    assert client.get(f"/receipts/{rid}/amendments").status_code == 401
    assert client.post(f"/receipts/{rid}/amendments", headers=HEADERS, json=body).status_code == 200
    store = ReceiptStore(Path(os.environ["DATABASE_PATH"]))
    with pytest.raises(DatabaseError):
        with store.connect() as db:
            db.execute("DELETE FROM amendment_audit")
    with pytest.raises(DatabaseError):
        with store.connect() as db:
            db.execute("UPDATE receipt_amendments SET result_json='{}'")
