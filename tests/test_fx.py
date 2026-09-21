from pathlib import Path
from uuid import uuid4

from app.dashboard import dashboard_summary
from app.database import ReceiptStore
from app.fx import convert_cents, parse_ecb_xml, set_workspace_currency
from app.main import get_fx_rate_provider, get_settings
from test_api import TEST_KEY, configured_client


HEADERS = {"X-API-Key": TEST_KEY}
RATES = {"EUR": "1", "SGD": "1.50", "MYR": "5.00", "USD": "1.20", "GBP": "0.85", "AUD": "1.80"}


class StubRates:
    calls = 0

    async def latest(self):
        self.calls += 1
        return {"as_of": "2026-09-18", "source": "European Central Bank", "rates": RATES}


def test_ecb_xml_parser_requires_every_supported_currency():
    cubes = "".join(
        f'<Cube currency="{currency}" rate="{rate}"/>'
        for currency, rate in RATES.items() if currency != "EUR"
    )
    result = parse_ecb_xml(
        f'<Envelope><Cube><Cube time="2026-09-18">{cubes}</Cube></Cube></Envelope>'.encode()
    )
    assert result == {"as_of": "2026-09-18", "source": "European Central Bank", "rates": RATES}


def accepted(store: ReceiptStore, currency: str, amount: float, receipt_date: str) -> None:
    receipt_id = str(uuid4())
    store.start(receipt_id, "image/jpeg", 10, "retained.jpg", None)
    store.complete({
        "receipt_id": receipt_id,
        "extracted_data": {"vendor": "Vendor", "date": receipt_date, "currency": currency,
                           "total_amount": amount, "line_items": []},
        "classification": {"workflow_decision": "AUTO_FILED", "category": "Office Supplies"},
    })


def test_cross_rate_conversion_and_consolidated_dashboard(tmp_path: Path):
    store = ReceiptStore(tmp_path / "fx.db")
    accepted(store, "SGD", 150.00, "2026-08-01")
    accepted(store, "MYR", 500.00, "2026-08-02")
    set_workspace_currency(store, "SGD")
    assert convert_cents(50_000, "MYR", "SGD", RATES) == 15_000
    result = dashboard_summary(store, {
        "as_of": "2026-09-18", "source": "European Central Bank", "rates": RATES,
        "stale": False,
    })
    assert result["default_currency"] == "SGD"
    assert result["reporting"]["available"] is True
    assert result["reporting"]["total_cents"] == 30_000
    assert result["reporting"]["months"] == [{"month": "2026-08", "total_cents": 30_000, "receipt_count": 2}]


def test_workspace_setting_latest_snapshot_cache_and_dashboard_api(monkeypatch, tmp_path: Path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    provider = StubRates()
    client.app.dependency_overrides[get_fx_rate_provider] = lambda: provider
    assert client.put("/workspace/settings", json={"default_currency": "SGD"}).status_code == 401
    saved = client.put("/workspace/settings", headers=HEADERS, json={"default_currency": "SGD"})
    assert saved.status_code == 200
    assert saved.headers["cache-control"] == "no-store"
    assert client.put("/workspace/settings", headers=HEADERS,
                      json={"default_currency": "XYZ"}).status_code == 422

    store = ReceiptStore(get_settings().database_path)
    accepted(store, "MYR", 100.00, "2026-09-01")
    first = client.get("/dashboard", headers=HEADERS).json()
    second = client.get("/dashboard", headers=HEADERS).json()
    assert first["reporting"]["total_cents"] == 3_000
    assert first["reporting"]["as_of"] == "2026-09-18"
    assert second["reporting"] == first["reporting"]
    assert provider.calls == 1

