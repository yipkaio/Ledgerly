from uuid import uuid4

from test_api import configured_client, TEST_KEY
from test_reviews import setup_review

HEADERS = {'X-API-Key': TEST_KEY}


def upload(client):
    return client.post('/receipts/upload', headers=HEADERS,
                       files={'receipt': ('original.jpg', b'\xff\xd8\xffdata', 'image/jpeg')}).json()['receipt_id']


def test_image_requires_auth_and_has_safe_headers(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    rid = upload(client)
    assert client.get(f'/receipts/{rid}/image').status_code == 401
    result = client.get(f'/receipts/{rid}/image', headers=HEADERS)
    assert result.status_code == 200
    assert result.content == b'\xff\xd8\xffdata'
    assert result.headers['content-type'] == 'image/jpeg'
    assert result.headers['cache-control'] == 'no-store'
    assert result.headers['x-content-type-options'] == 'nosniff'
    assert client.get(f'/receipts/{uuid4()}/image', headers=HEADERS).status_code == 404


def test_missing_invalid_and_oversized_images_are_controlled(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    rid = upload(client)
    path = tmp_path / f'{rid}.jpg'
    path.write_bytes(b'<html>not an image</html>')
    assert client.get(f'/receipts/{rid}/image', headers=HEADERS).status_code == 404
    path.write_bytes(b'\xff\xd8\xff' + b'x' * 5242880)
    assert client.get(f'/receipts/{rid}/image', headers=HEADERS).status_code == 404
    path.unlink()
    assert client.get(f'/receipts/{rid}/image', headers=HEADERS).status_code == 404


def test_symlink_cannot_escape_upload_directory(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    rid = upload(client)
    path = tmp_path / f'{rid}.jpg'
    outside = tmp_path.parent / f'{uuid4()}.jpg'
    outside.write_bytes(b'\xff\xd8\xffprivate')
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        import pytest
        pytest.skip('Symlinks unavailable on this platform')
    assert client.get(f'/receipts/{rid}/image', headers=HEADERS).status_code == 404


def test_image_does_not_trust_database_path(monkeypatch, tmp_path):
    client, original, _, store = setup_review(monkeypatch, tmp_path)
    rid = original['receipt_id']
    with store.connect() as db:
        db.execute('UPDATE receipts SET image_path=? WHERE receipt_id=?', ('/private/outside.jpg', rid))
    result = client.get(f'/receipts/{rid}/image', headers=HEADERS)
    assert result.status_code == 200
    assert result.content == b'\xff\xd8\xffdata'


def test_built_ui_is_public_but_data_is_private(monkeypatch, tmp_path):
    from pathlib import Path
    from app.main import create_app
    from fastapi.testclient import TestClient
    if not (Path(__file__).parent.parent / 'frontend' / 'dist' / 'index.html').exists():
        import pytest
        pytest.skip('Build frontend first to verify static serving')
    client, *_ = configured_client(monkeypatch, tmp_path)
    monkeypatch.setenv('API_DOCS_ENABLED', 'false')
    client = TestClient(create_app())
    shell = client.get('/ui/')
    assert shell.status_code == 200
    assert TEST_KEY not in shell.text
    assert shell.headers['cache-control'] == 'no-store'
    assert "frame-ancestors 'none'" in shell.headers['content-security-policy']
    assert client.get('/docs').status_code == 404
    assert client.get('/receipts').status_code == 401
    assert client.get('/receipts').headers['cache-control'] == 'no-store'


def test_history_shows_final_review_metadata(monkeypatch, tmp_path):
    client, original, body, _ = setup_review(monkeypatch, tmp_path)
    pending = client.get('/reviews', headers=HEADERS).json()['items'][0]
    assert pending['vendor'] == original['extracted_data']['vendor']
    body['corrected_data']['vendor'] = 'Verified vendor'
    assert client.post(f"/receipts/{original['receipt_id']}/review", headers=HEADERS, json=body).status_code == 200
    row = client.get('/receipts', headers=HEADERS).json()['items'][0]
    assert row['vendor'] == 'Verified vendor'
    assert row['review_decision'] == 'APPROVED'
    assert client.get('/reviews', headers=HEADERS).json()['total'] == 0
