import copy
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import DatabaseError, ReceiptStore, SCHEMA
from app.main import create_app
from app.review import ReviewRequest, ReviewConflict, submit_review
from test_api import configured_client, TEST_KEY

HEADERS = {"X-API-Key": TEST_KEY}


def setup_review(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)
    extractor.needs_review = True
    uploaded = client.post('/receipts/upload', headers=HEADERS,
                           files={'receipt': ('a.jpg', b'\xff\xd8\xffdata', 'image/jpeg')}).json()
    body = dict(request_id=str(uuid4()), expected_version=0, decision='APPROVED',
                reviewer='Local reviewer', note='Checked against original receipt image',
                evidence_confirmed=True, corrected_data=uploaded['extracted_data'], category='Office Supplies')
    return client, uploaded, body, ReceiptStore(Path(os.environ['DATABASE_PATH']))


def test_approval_preserves_evidence_and_survives_restart(monkeypatch, tmp_path):
    client, original, body, store = setup_review(monkeypatch, tmp_path)
    rid = original['receipt_id']
    assert client.get('/reviews', headers=HEADERS).json()['total'] == 1
    body['corrected_data'] = copy.deepcopy(body['corrected_data'])
    body['corrected_data']['vendor'] = 'Verified vendor'
    response = client.post(f'/receipts/{rid}/review', headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['identity_source'] == 'self_reported'
    assert response.json()['final_data']['needs_review'] is False
    assert client.get('/reviews', headers=HEADERS).json()['total'] == 0
    saved = TestClient(create_app()).get(f'/receipts/{rid}', headers=HEADERS).json()
    assert saved['extracted_data'] == original['extracted_data']
    assert saved['classification'] == original['classification']
    assert saved['review']['final_data']['vendor'] == 'Verified vendor'
    assert saved['review_version'] == 1
    history = client.get(f'/receipts/{rid}/reviews', headers=HEADERS).json()['items']
    assert len(history) == 1
    assert history[0]['before']['extracted_data'] == original['extracted_data']
    assert 'image_path' not in str(history)
    with pytest.raises(DatabaseError):
        with store.connect() as db:
            db.execute('DELETE FROM review_audit')


def test_idempotent_retry_and_conflict(monkeypatch, tmp_path):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    url = f"/receipts/{original['receipt_id']}/review"
    first = client.post(url, headers=HEADERS, json=body)
    assert client.post(url, headers=HEADERS, json=body).json() == first.json()
    body['note'] = 'Different note'
    assert client.post(url, headers=HEADERS, json=body).status_code == 409
    body['request_id'] = str(uuid4())
    assert client.post(url, headers=HEADERS, json=body).status_code == 409


@pytest.mark.parametrize('change', [
    {'reviewer': ' '}, {'note': ''}, {'evidence_confirmed': False},
    {'expected_version': -1}, {'expected_version': True}, {'decision': 'AUTO_FILED'},
    {'category': 'Invented'}, {'corrected_data': None}, {'unknown': 'field'},
])
def test_invalid_boundaries(monkeypatch, tmp_path, change):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    body.update(change)
    assert client.post(f"/receipts/{original['receipt_id']}/review", headers=HEADERS, json=body).status_code == 422


def test_all_review_routes_require_auth(monkeypatch, tmp_path):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    rid = original['receipt_id']
    assert client.get('/reviews').status_code == 401
    assert client.get(f'/receipts/{rid}/reviews').status_code == 401
    assert client.post(f'/receipts/{rid}/review', json=body).status_code == 401
    assert client.get('/reviews?limit=101', headers=HEADERS).status_code == 422
    assert client.get('/reviews?offset=-1', headers=HEADERS).status_code == 422


def test_arithmetic_override_is_explicit(monkeypatch, tmp_path):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    url = f"/receipts/{original['receipt_id']}/review"
    body['corrected_data']['total_amount'] = 99
    assert client.post(url, headers=HEADERS, json=body).status_code == 422
    assert client.get('/reviews', headers=HEADERS).json()['total'] == 1
    body['override_reason'] = 'Accepted exceptional printed discrepancy after checking image'
    response = client.post(url, headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.json()['validation_issues']
    assert response.json()['final_data']['total_amount'] == 99


def test_no_silent_swap(monkeypatch, tmp_path):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    body['corrected_data']['line_items'] = [dict(description='Ruler', quantity=1, unit_price=5.69,
                                               discount_percent=3.5, line_total=3.3)]
    body['override_reason'] = 'Reviewed discrepancy with receipt issuer'
    response = client.post(f"/receipts/{original['receipt_id']}/review", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.json()['final_data']['line_items'][0]['unit_price'] == 5.69
    assert any('price and discount' in x for x in response.json()['validation_issues'])


def test_rejection_and_missing(monkeypatch, tmp_path):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    body.update(decision='REJECTED', corrected_data=None, category=None)
    assert client.post(f"/receipts/{uuid4()}/review", headers=HEADERS, json=body).status_code == 404
    assert client.get(f"/receipts/{uuid4()}/reviews", headers=HEADERS).status_code == 404
    response = client.post(f"/receipts/{original['receipt_id']}/review", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.json()['decision'] == 'REJECTED'
    assert client.get('/reviews', headers=HEADERS).json()['total'] == 0


def test_racing_reviewers_only_one_commits(monkeypatch, tmp_path):
    _, original, body, store = setup_review(monkeypatch, tmp_path)
    def submit(_):
        request = ReviewRequest.model_validate({**body, 'request_id': str(uuid4())})
        try:
            submit_review(store, original['receipt_id'], request)
            return 'ok'
        except ReviewConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == ['conflict', 'ok']


def test_audit_failure_rolls_back_decision(monkeypatch, tmp_path):
    client, original, body, store = setup_review(monkeypatch, tmp_path)
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON review_audit BEGIN SELECT RAISE(ABORT, 'private'); END")
    response = client.post(f"/receipts/{original['receipt_id']}/review", headers=HEADERS, json=body)
    assert response.status_code == 503
    assert 'private' not in response.text
    assert store.get(original['receipt_id'])['review'] is None


def test_existing_v1_migrates_without_changing_evidence(tmp_path):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as db:
        for sql in SCHEMA:
            db.execute(sql)
        db.execute("INSERT INTO receipts (receipt_id,content_type,size_bytes,image_path,processing_status,created_at,updated_at) VALUES ('old','image/jpeg',10,'secret','FAILED','date','date')")
        db.execute('PRAGMA user_version=1')
    store = ReceiptStore(path)
    assert store.get('old')['processing_status'] == 'FAILED'
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert db.execute('SELECT image_path FROM receipts').fetchone()[0] == 'secret'
        assert db.execute('SELECT count(*) FROM vendor_category_mappings').fetchone()[0] == 0
