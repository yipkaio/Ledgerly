import json

from app.dashboard import dashboard_summary
from app.database import ReceiptStore
from test_api import configured_client, TEST_KEY
from test_reviews import setup_review

HEADERS = {'X-API-Key': TEST_KEY}


def test_dashboard_auth_empty_snapshot_and_privacy(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    assert client.get('/dashboard').status_code == 401
    response = client.get('/dashboard', headers=HEADERS)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['total_receipts'] == 0
    assert response.json()['currencies'] == []


def test_dashboard_uses_human_final_values_and_excludes_rejections(monkeypatch, tmp_path):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    assert client.get('/dashboard', headers=HEADERS).json()['counts']['REVIEW_QUEUE'] == 1
    assert client.get('/dashboard', headers=HEADERS).json()['currencies'] == []
    body['category'] = 'Repairs and Maintenance'
    body['corrected_data']['currency'] = 'SGD'
    body['corrected_data']['date'] = '2026-09-01'
    assert client.post(f"/receipts/{original['receipt_id']}/review", headers=HEADERS, json=body).status_code == 200
    result = client.get('/dashboard', headers=HEADERS).json()
    assert result['counts']['REVIEW_QUEUE'] == 0
    assert result['counts']['APPROVED'] == 1
    assert result['currencies'] == [{'currency': 'SGD', 'total_cents': 3390, 'receipt_count': 1,
                                    'categories': [{'category': 'Repairs and Maintenance', 'total_cents': 3390}],
                                    'months': [{'month': '2026-09', 'total_cents': 3390}]}]
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    rejection = {k: v for k, v in body.items() if k not in ('category', 'corrected_data')}
    rejection['decision'] = 'REJECTED'
    assert client.post(f"/receipts/{original['receipt_id']}/review", headers=HEADERS, json=rejection).status_code == 200
    result = client.get('/dashboard', headers=HEADERS).json()
    assert result['counts']['REJECTED'] == 1
    assert result['currencies'][0]['total_cents'] == 3390


def test_dashboard_keeps_currencies_separate_uses_cents_and_bounds_trend(tmp_path):
    store = ReceiptStore(tmp_path / 'summary.db')
    for i in range(14):
        store.start(str(i), 'image/jpeg', 10, 'path', None)
        store.complete({'receipt_id': str(i), 'extracted_data': {'line_items': [], 'total_amount': 0.1,
                       'currency': 'MYR' if i < 13 else 'SGD', 'date': f'{2020 + i}-01-01'},
                        'classification': {'workflow_decision': 'AUTO_FILED', 'category': 'Office Supplies'}})
    store.start('missing-value', 'image/jpeg', 10, 'path', None)
    store.complete({'receipt_id': 'missing-value', 'extracted_data': {'line_items': [], 'total_amount': None, 'currency': None},
                    'classification': {'workflow_decision': 'AUTO_FILED'}})
    store.start('failed', 'image/jpeg', 10, 'path', None)
    store.fail('failed', 'Controlled failure')
    summary = dashboard_summary(store)
    myr, sgd = summary['currencies']
    assert myr['total_cents'] == 130
    assert sgd['total_cents'] == 10
    assert len(myr['months']) == 12
    assert myr['months'][0]['month'] == '2021-01'
    assert summary['accepted_missing_value'] == 1
    assert summary['counts']['FAILED'] == 1
    assert summary['total_receipts'] == 16
    assert 'path' not in json.dumps(summary)
