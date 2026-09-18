from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.database import DatabaseError
from app.lifecycle import purge_expired
from test_reviews import setup_review, HEADERS
from test_duplicates_amendments import amendment_body


def body(action, version=0, record_version=0):
    return dict(request_id=str(uuid4()), action=action, expected_version=version,
                expected_record_version=record_version, reviewer='Test reviewer',
                reason='Synthetic test receipt entered by mistake')


def change(client, rid, request):
    return client.post(f'/receipts/{rid}/lifecycle', headers=HEADERS, json=request)


def test_delete_restore_and_idempotency(monkeypatch, tmp_path):
    client, receipt, review, store = setup_review(monkeypatch, tmp_path)
    rid = receipt['receipt_id']
    request = body('DELETE')
    result = change(client, rid, request)
    assert result.status_code == 200, result.text
    event = result.json()
    assert datetime.fromisoformat(event['purge_after']) - datetime.fromisoformat(event['occurred_at']) == timedelta(days=30)
    assert change(client, rid, request).json() == event
    assert len(store.get(rid)['lifecycle_events']) == 1
    assert client.get('/reviews', headers=HEADERS).json()['total'] == 0
    assert client.get('/receipts', headers=HEADERS).json()['total'] == 0
    assert client.get('/receipts?state=DELETED', headers=HEADERS).json()['total'] == 1
    assert client.get('/dashboard', headers=HEADERS).json()['total_receipts'] == 0
    assert client.post(f'/receipts/{rid}/review', headers=HEADERS, json=review).status_code == 409
    assert client.post('/receipts/export', headers=HEADERS, json={'receipt_ids': [rid]}).status_code == 422
    assert client.post('/receipts/export', headers=HEADERS, json={'filters': {'state': 'DELETED'}}).headers['X-Receipt-Count'] == '0'
    assert purge_expired(store, tmp_path) == 0
    assert change(client, rid, body('RESTORE', 1)).status_code == 200
    assert client.get('/reviews', headers=HEADERS).json()['total'] == 1
    assert store.get(rid)['extracted_data'] == receipt['extracted_data']
    assert change(client, rid, body('DELETE')).status_code == 409
    with pytest.raises(DatabaseError):
        with store.connect() as db:
            db.execute('DELETE FROM lifecycle_events')


@pytest.mark.parametrize('approved', [True, False])
def test_void_preserves_evidence_and_excludes_totals(monkeypatch, tmp_path, approved):
    client, receipt, review, store = setup_review(monkeypatch, tmp_path)
    rid = receipt['receipt_id']
    if approved:
        assert client.post(f'/receipts/{rid}/review', headers=HEADERS, json=review).status_code == 200
    else:
        with store.connect() as db:
            db.execute("UPDATE receipts SET processing_status='COMPLETED' WHERE receipt_id=?", (rid,))
            db.execute("UPDATE classifications SET decision='AUTO_FILED' WHERE receipt_id=?", (rid,))
    version = 1 if approved else 0
    assert change(client, rid, body('DELETE', record_version=version)).status_code == 409
    assert change(client, rid, body('VOID', record_version=version)).status_code == 200
    current = store.get(rid)
    assert current['extracted_data'] == receipt['extracted_data']
    assert current['lifecycle_state'] == 'VOIDED'
    assert current['purge_after'] is None
    assert client.get('/dashboard', headers=HEADERS).json()['currencies'] == []
    assert client.get('/receipts?state=VOIDED', headers=HEADERS).json()['total'] == 1
    assert client.post('/receipts/export', headers=HEADERS, json={}).headers['X-Receipt-Count'] == '0'
    assert client.post('/receipts/export', headers=HEADERS, json={'receipt_ids': [rid]}).status_code == 422
    assert change(client, rid, body('DELETE', 1, version)).status_code == 409
    assert change(client, rid, body('RESTORE', 1, version)).status_code == 409
    assert client.post(f'/receipts/{rid}/amendments', headers=HEADERS, json=amendment_body(current)).status_code == 409
    assert purge_expired(store, tmp_path) == 0
    assert store.get(rid) is not None
    if approved:
        with pytest.raises(DatabaseError):
            with store.connect() as db:
                db.execute('DELETE FROM review_audit')


def test_reupload_allowed_and_restore_conflicts(monkeypatch, tmp_path):
    client, receipt, _, store = setup_review(monkeypatch, tmp_path)
    rid = receipt['receipt_id']
    assert change(client, rid, body('DELETE')).status_code == 200
    uploaded = client.post('/receipts/upload', headers=HEADERS, files={'receipt': ('a.jpg', b'\xff\xd8\xffdata', 'image/jpeg')})
    assert uploaded.status_code == 202, uploaded.text
    assert uploaded.json()['receipt_id'] != rid
    assert change(client, rid, body('RESTORE', 1)).status_code == 409
    assert store.get(rid)['lifecycle_state'] == 'DELETED'


@pytest.mark.parametrize('rejected', [True, False])
def test_purge_only_expired_deleted_files_and_rows(monkeypatch, tmp_path, rejected):
    client, receipt, review, store = setup_review(monkeypatch, tmp_path)
    rid = receipt['receipt_id']
    if rejected:
        review.update(decision='REJECTED', corrected_data=None, category=None)
        assert client.post(f'/receipts/{rid}/review', headers=HEADERS, json=review).status_code == 200
    assert change(client, rid, body('DELETE', record_version=int(rejected))).status_code == 200
    original = tmp_path / f'{rid}.jpg'
    assert original.exists()
    unrelated = tmp_path / 'keep.txt'
    unrelated.write_text('Unrelated file')
    with store.connect() as db:
        db.execute("UPDATE receipts SET purge_after=?, image_path=? WHERE receipt_id=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), str(unrelated), rid))
    assert change(client, rid, body('RESTORE', 1, int(rejected))).status_code == 409
    assert purge_expired(store, tmp_path) == 1
    assert not original.exists()
    assert unrelated.exists()
    assert store.get(rid) is None
    assert purge_expired(store, tmp_path) == 0


def test_auth_validation_processing_and_stale_review(monkeypatch, tmp_path):
    client, receipt, review, store = setup_review(monkeypatch, tmp_path)
    rid = receipt['receipt_id']
    assert client.post(f'/receipts/{rid}/lifecycle', json=body('DELETE')).status_code == 401
    invalid = body('DELETE'); invalid['reason'] = ' '
    assert change(client, rid, invalid).status_code == 422
    assert change(client, rid, body('VOID')).status_code == 409
    with store.connect() as db:
        db.execute("UPDATE receipts SET processing_status='PROCESSING' WHERE receipt_id=?", (rid,))
    assert change(client, rid, body('DELETE')).status_code == 409
    with store.connect() as db:
        db.execute("UPDATE receipts SET processing_status='REVIEW_QUEUE' WHERE receipt_id=?", (rid,))
    assert client.post(f'/receipts/{rid}/review', headers=HEADERS, json=review).status_code == 200
    assert change(client, rid, body('VOID')).status_code == 409
