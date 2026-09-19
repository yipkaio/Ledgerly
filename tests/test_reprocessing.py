import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.database import DatabaseError
from app.reprocessing import ReprocessRequest, begin, finish
from test_reviews import setup_review, HEADERS
from test_duplicates_amendments import amendment_body


def request_body(receipt=None):
    return dict(request_id=str(uuid4()), expected_record_version=(receipt or {}).get('record_version', 0),
                expected_lifecycle_version=0, reviewer='Test reviewer', reason='Extract discount using updated extraction prompt')


def test_draft_does_not_change_original_or_totals_and_retries_do_not_call_ai(monkeypatch, tmp_path):
    client, uploaded, review, store = setup_review(monkeypatch, tmp_path)
    rid = uploaded['receipt_id']
    assert client.post(f'/receipts/{rid}/review', headers=HEADERS, json=review).status_code == 200
    original = store.get(rid)
    from app.main import get_receipt_extractor
    extractor = client.app.dependency_overrides[get_receipt_extractor]()
    extractor.vendor = 'New extraction vendor'
    request = request_body(original)
    url = f'/receipts/{rid}/reprocess'
    before_calls = len(extractor.inputs)
    totals = client.get('/dashboard', headers=HEADERS).json()['currencies']
    result = client.post(url, headers=HEADERS, json=request)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'SUCCEEDED'
    assert client.post(url, headers=HEADERS, json=request).json() == result.json()
    assert len(extractor.inputs) == before_calls + 1
    after = store.get(rid)
    for key in ('extracted_data', 'ocr_text', 'review', 'effective_data', 'effective_category'):
        assert after[key] == original[key]
    assert client.get('/dashboard', headers=HEADERS).json()['currencies'] == totals
    amendment = amendment_body(after)
    amendment.update(final_data=result.json()['extracted_data'], reprocess_request_id=request['request_id'])
    saved = client.post(f'/receipts/{rid}/amendments', headers=HEADERS, json=amendment)
    assert saved.status_code == 200, saved.text
    assert saved.json()['reprocess_request_id'] == request['request_id']
    assert store.get(rid)['extracted_data'] == original['extracted_data']
    assert store.get(rid)['effective_data']['vendor'] == 'New extraction vendor'
    with pytest.raises(DatabaseError):
        with store.connect() as db:
            db.execute("UPDATE receipt_reprocessing SET status='FAILED'")


def test_failure_and_failed_receipt_recovery_requires_review(monkeypatch, tmp_path):
    client, uploaded, review, store = setup_review(monkeypatch, tmp_path)
    rid = uploaded['receipt_id']
    from app.main import get_receipt_extractor
    extractor = client.app.dependency_overrides[get_receipt_extractor]()
    extractor.error = RuntimeError('secret upstream diagnostic')
    url = f'/receipts/{rid}/reprocess'
    result = client.post(url, headers=HEADERS, json=request_body()).json()
    assert result['status'] == 'FAILED'
    assert 'secret' not in json.dumps(result)
    assert store.get(rid)['extracted_data'] == uploaded['extracted_data']
    extractor.error = None
    # Simulate original extraction failing after OCR was safely retained.
    with store.connect() as db:
        db.execute('DELETE FROM line_items WHERE receipt_id=?', (rid,))
        db.execute('DELETE FROM classifications WHERE receipt_id=?', (rid,))
        db.execute("UPDATE receipts SET extraction_json=NULL, processing_status='FAILED', error='Original extraction failed' WHERE receipt_id=?", (rid,))
    draft = client.post(url, headers=HEADERS, json=request_body()).json()
    assert draft['status'] == 'SUCCEEDED'
    recovered = store.get(rid)
    assert recovered['extracted_data'] is None
    assert recovered['error'] == 'Original extraction failed'
    assert recovered['processing_status'] == 'REVIEW_QUEUE'
    review.update(corrected_data=draft['extracted_data'], reprocess_request_id=draft['request_id'])
    response = client.post(f'/receipts/{rid}/review', headers=HEADERS, json=review)
    assert response.status_code == 200, response.text
    assert store.get(rid)['effective_data'] == response.json()['final_data']


def test_running_and_stale_attempts_cannot_overwrite_decisions(monkeypatch, tmp_path):
    client, uploaded, review, store = setup_review(monkeypatch, tmp_path)
    rid = uploaded['receipt_id']
    request = ReprocessRequest(**request_body())
    started, text = begin(store, rid, request, 'test-model')
    assert text
    assert begin(store, rid, request, 'test-model')[1] is None
    assert client.post(f'/receipts/{rid}/reprocess', headers=HEADERS, json=request_body()).status_code == 409
    assert client.post(f'/receipts/{rid}/review', headers=HEADERS, json=review).status_code == 200
    completed = finish(store, rid, request, uploaded['extracted_data'])
    assert completed['status'] == 'SUPERSEDED'
    assert store.get(rid)['review']['decision'] == 'APPROVED'
    amendment = amendment_body(store.get(rid))
    amendment['reprocess_request_id'] = started['request_id']
    assert client.post(f'/receipts/{rid}/amendments', headers=HEADERS, json=amendment).status_code == 409


def test_auth_eligibility_collision_and_interrupted_retry(monkeypatch, tmp_path):
    client, uploaded, _, store = setup_review(monkeypatch, tmp_path)
    rid = uploaded['receipt_id']; url = f'/receipts/{rid}/reprocess'
    body = request_body()
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, headers=HEADERS, json={**body, 'reason': ' '}).status_code == 422
    request = ReprocessRequest(**body)
    begin(store, rid, request, 'test-model')
    assert client.post(url, headers=HEADERS, json={**body, 'reason': 'Different reason for the same request'}).status_code == 409
    with store.connect() as db:
        db.execute('UPDATE receipt_reprocessing SET expires_at=?', ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    assert client.post(url, headers=HEADERS, json=body).json()['status'] == 'FAILED'
    with store.connect() as db:
        db.execute("UPDATE receipts SET ocr_text=NULL WHERE receipt_id=?", (rid,))
    assert client.post(url, headers=HEADERS, json=request_body()).status_code == 409


def test_draft_purges_only_with_expired_deleted_receipt(monkeypatch, tmp_path):
    from app.lifecycle import purge_expired
    from test_lifecycle import body, change
    client, uploaded, _, store = setup_review(monkeypatch, tmp_path)
    rid = uploaded['receipt_id']
    assert client.post(f'/receipts/{rid}/reprocess', headers=HEADERS, json=request_body()).json()['status'] == 'SUCCEEDED'
    assert change(client, rid, body('DELETE')).status_code == 200
    assert purge_expired(store, tmp_path) == 0
    with store.connect() as db:
        db.execute('UPDATE receipts SET purge_after=? WHERE receipt_id=?', ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), rid))
    assert purge_expired(store, tmp_path) == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM receipt_reprocessing').fetchone()[0] == 0


def test_pre_v5_request_retry_remains_identical():
    from app.review import same_saved_request
    assert same_saved_request('{"request_id":"same"}', '{"request_id":"same","reprocess_request_id":null}')
    assert not same_saved_request('{"request_id":"same"}', '{"request_id":"same","reprocess_request_id":"different"}')
