from decimal import Decimal
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from app.database import ReceiptStore
from app.exporting import ExportRequest, build_export
from app.extraction import ReceiptExtraction
from test_api import TEST_KEY, configured_client
from test_duplicates_amendments import amendment_body
from xlsx_assertions import sheet_cells


HEADERS = {"X-API-Key": TEST_KEY}


def upload(client, content: bytes):
    response = client.post(
        "/receipts/upload",
        headers=HEADERS,
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xff" + content, "image/jpeg")},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_history_filters_use_latest_effective_values(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)
    first = upload(client, b"one")
    second = upload(client, b"two")
    detail = client.get(f"/receipts/{first['receipt_id']}", headers=HEADERS).json()
    body = amendment_body(
        detail,
        vendor="Corrected 100% Supplies_Store",
        receipt_number="INV-200",
        date="2024-04-05",
        currency="SGD",
    )
    assert client.post(
        f"/receipts/{first['receipt_id']}/amendments", headers=HEADERS, json=body
    ).status_code == 200

    page = client.get(
        "/receipts?query=100%25%20Supplies_Store&currency=SGD&state=AMENDED"
        "&category=Office%20Supplies&date_from=2024-04-01&date_to=2024-04-30",
        headers=HEADERS,
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1
    row = page.json()["items"][0]
    assert row["receipt_id"] == first["receipt_id"]
    assert row["vendor"] == "Corrected 100% Supplies_Store"
    assert row["receipt_number"] == "INV-200"
    assert row["receipt_date"] == "2024-04-05"
    assert row["workflow_state"] == "AMENDED"
    assert client.get("/receipts?vendor=MR%20DIY", headers=HEADERS).json()["total"] == 1
    assert client.get("/receipts?query=" + second["receipt_id"][:8], headers=HEADERS).json()["total"] == 1
    assert client.get(
        "/receipts?date_from=2025-01-01&date_to=2024-01-01", headers=HEADERS
    ).status_code == 422

    multi = client.get(
        "/receipts?currency=SGD&currency=MYR&state=AMENDED&state=AUTO_FILED",
        headers=HEADERS,
    )
    assert multi.status_code == 200, multi.text
    assert multi.json()["total"] == 2


def test_selected_export_has_polished_safe_effective_sheets(monkeypatch, tmp_path):
    client, _, extractor, _ = configured_client(monkeypatch, tmp_path)

    async def formula_data(text):
        base = await original(text)
        values = base.model_dump(mode="json")
        values["vendor"] = "=HYPERLINK(\"https://evil.invalid\")"
        values["receipt_number"] = "R-1"
        values["discount_amount"] = 5.00
        values["line_items"] = [{
            "description": "+cmd|' /C calc'!A0",
            "quantity": 1,
            "unit_price": 33.90,
            "discount_percent": None,
            "discount_amount": None,
            "line_total": 33.90,
        }]
        return ReceiptExtraction.model_validate(values)

    original = extractor.extract
    extractor.extract = formula_data
    receipt = upload(client, b"formula")
    response = client.post(
        "/receipts/export",
        headers=HEADERS,
        json={"receipt_ids": [receipt["receipt_id"]]},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["x-receipt-count"] == "1"
    assert "receipt-history.xlsx" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"

    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        workbook = archive.read("xl/workbook.xml").decode()
        strings = archive.read("xl/sharedStrings.xml").decode()
        worksheets = "".join(
            archive.read(name).decode()
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet")
        )
    assert all(name in workbook for name in ("Overview", "Receipts", "Line items", "Review audit"))
    assert all(value in strings for value in ("Accepted spend by currency", "Workflow status", "Accepted spend by category and currency"))
    assert any(name.startswith("xl/tables/table") for name in names)
    assert "HYPERLINK" in strings and "cmd|' /C calc'!A0" in strings
    assert "Receipt Discount" in strings
    assert "<f>" not in worksheets


def test_receipt_overview_excludes_pending_values_and_keeps_currencies_separate(tmp_path):
    store = ReceiptStore(tmp_path / "expenses.db")
    ids = []
    for vendor, currency, amount, state in (
        ("Approved supplier", "SGD", 12.34, "AUTO_FILED"),
        ("Pending supplier", "SGD", 99.99, "REVIEW_QUEUE"),
        ("Another currency", "MYR", 23.45, "AUTO_FILED"),
    ):
        receipt_id = str(uuid4())
        store.start(receipt_id, "image/jpeg", 10, "source.jpg", None)
        store.complete({
            "receipt_id": receipt_id,
            "extracted_data": {"vendor": vendor, "date": "2026-09-18", "currency": currency,
                               "total_amount": amount, "line_items": ([{
                                   "description": "Office item", "quantity": 1, "unit_price": 13.71,
                                   "discount_percent": 10, "discount_amount": 1.37,
                                   "line_total": 12.34,
                               }] if vendor == "Approved supplier" else [])},
            "classification": {"workflow_decision": state, "category": "Office Supplies"},
        })
        ids.append(receipt_id)
    workbook, count = build_export(store, ExportRequest(receipt_ids=ids))
    assert count == 3
    overview = sheet_cells(workbook, 1)
    assert (overview["A12"], overview["B12"], overview["C12"], overview["E12"]) == (
        "MYR", 1, 1, Decimal("23.45"),
    )
    assert (overview["A13"], overview["B13"], overview["C13"], overview["D13"], overview["E13"]) == (
        "SGD", 2, 1, 1, Decimal("12.34"),
    )
    assert "Pending supplier" in sheet_cells(workbook, 2).values()
    assert Decimal("99.99") not in overview.values()
    assert sheet_cells(workbook, 3)["F6"] == 10
    with ZipFile(BytesIO(workbook)) as archive:
        assert '0.##&quot;%&quot;' in archive.read("xl/styles.xml").decode()


def test_filtered_export_and_selection_validation(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    upload(client, b"one")
    upload(client, b"two")
    response = client.post(
        "/receipts/export",
        headers=HEADERS,
        json={"filters": {"vendor": "MR DIY", "currency": "MYR"}},
    )
    assert response.status_code == 200
    assert response.headers["x-receipt-count"] == "2"

    multi = client.post(
        "/receipts/export",
        headers=HEADERS,
        json={"filters": {"currency": ["SGD", "MYR"], "state": ["AUTO_FILED"]}},
    )
    assert multi.status_code == 200
    assert multi.headers["x-receipt-count"] == "2"
    assert client.post("/receipts/export", json={"filters": {}}).status_code == 401
    assert client.post(
        "/receipts/export", headers=HEADERS, json={"receipt_ids": []}
    ).status_code == 422
    assert client.post(
        "/receipts/export", headers=HEADERS, json={"receipt_ids": [str(uuid4())]}
    ).status_code == 422
    assert client.post(
        "/receipts/export",
        headers=HEADERS,
        json={"filters": {"date_from": "2025-01-01", "date_to": "2024-01-01"}},
    ).status_code == 422
