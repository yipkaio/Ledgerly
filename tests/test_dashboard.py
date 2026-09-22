import json
from datetime import date

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
    client, original, body, _ = setup_review(monkeypatch, tmp_path, b'\xff\xd8\xffdifferent')
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
                                    'months': [{'month': '2026-09', 'total_cents': 3390,
                                                'receipt_count': 1}]}]
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
    assert len(myr['months']) == 13
    assert myr['months'][0]['month'] == '2020-01'
    assert summary['accepted_missing_value'] == 1
    assert summary['counts']['FAILED'] == 1
    assert summary['total_receipts'] == 16
    assert 'path' not in json.dumps(summary)


def test_dashboard_date_range_filters_accepted_data_but_not_workspace_counts(tmp_path):
    store = ReceiptStore(tmp_path / 'range.db')
    for receipt_id, receipt_date, amount, category in (
        ('old', '2025-12-31', 10.00, 'Office Supplies'),
        ('inside', '2026-09-18', 20.00, 'Travel and Transport'),
        ('new', '2026-10-01', 30.00, 'Meals and Entertainment'),
    ):
        store.start(receipt_id, 'image/jpeg', 10, 'path', None)
        store.complete({
            'receipt_id': receipt_id,
            'extracted_data': {
                'line_items': [], 'total_amount': amount,
                'currency': 'SGD', 'date': receipt_date,
            },
            'classification': {
                'workflow_decision': 'AUTO_FILED', 'category': category,
            },
        })
    summary = dashboard_summary(
        store,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert summary['counts']['AUTO_FILED'] == 3
    assert summary['total_receipts'] == 3
    assert summary['accepted_count'] == 1
    assert summary['accepted_date_bounds'] == {
        'first': '2025-12-31', 'last': '2026-10-01',
    }
    assert summary['date_range'] == {
        'from': '2026-09-01', 'to': '2026-09-30',
    }
    assert summary['currencies'] == [{
        'currency': 'SGD',
        'total_cents': 2000,
        'receipt_count': 1,
        'categories': [{
            'category': 'Travel and Transport', 'total_cents': 2000,
        }],
        'months': [{
            'month': '2026-09', 'total_cents': 2000, 'receipt_count': 1,
        }],
    }]


def test_dashboard_rejects_reversed_date_range(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    response = client.get(
        '/dashboard?date_from=2026-10-01&date_to=2026-09-01',
        headers=HEADERS,
    )
    assert response.status_code == 422
    assert response.json()['detail'] == 'date_from must be on or before date_to'


def test_all_time_dated_receipts_tracks_new_entries_and_omits_undated(tmp_path):
    store = ReceiptStore(tmp_path / 'all_time.db')

    def add(receipt_id, receipt_date):
        store.start(receipt_id, 'image/jpeg', 10, 'path', None)
        store.complete({
            'receipt_id': receipt_id,
            'extracted_data': {
                'line_items': [], 'total_amount': 5.00,
                'currency': 'SGD', 'date': receipt_date,
            },
            'classification': {
                'workflow_decision': 'AUTO_FILED', 'category': 'Office Supplies',
            },
        })

    add('first', '2025-01-01')
    add('undated', None)
    first = dashboard_summary(store, dated_only=True)
    assert first['accepted_count'] == 1
    assert first['currencies'][0]['total_cents'] == 500
    assert first['accepted_date_bounds'] == {'first': '2025-01-01', 'last': '2025-01-01'}

    add('recent', '2026-09-18')
    refreshed = dashboard_summary(store, dated_only=True)
    assert refreshed['accepted_count'] == 2
    assert refreshed['currencies'][0]['total_cents'] == 1000
    assert refreshed['accepted_date_bounds']['last'] == '2026-09-18'
    assert dashboard_summary(store)['accepted_count'] == 3


def test_all_time_dated_endpoint_filters_undated(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    response = client.get('/dashboard?dated_only=true', headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['accepted_count'] == 0
    assert response.json()['accepted_date_bounds'] == {'first': None, 'last': None}
