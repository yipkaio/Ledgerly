from pathlib import Path
from uuid import uuid4

from app.database import ReceiptStore
from app.main import get_settings
from app.statements import build_monthly_export, monthly_reconciliation, parse_statement_csv
from test_api import TEST_KEY, configured_client


HEADERS = {"X-API-Key": TEST_KEY}


def accepted(store: ReceiptStore, vendor: str, amount: float, receipt_date: str) -> str:
    receipt_id = str(uuid4())
    store.start(receipt_id, "image/jpeg", 10, "retained.jpg", None)
    store.complete({
        "receipt_id": receipt_id,
        "extracted_data": {
            "vendor": vendor, "date": receipt_date, "currency": "SGD",
            "total_amount": amount, "line_items": [],
        },
        "classification": {
            "workflow_decision": "AUTO_FILED", "category": "Repairs and Maintenance",
        },
    })
    return receipt_id


def test_csv_parser_handles_debit_and_signed_amount_safely():
    rows, skipped = parse_statement_csv(
        b"Date,Description,Debit,Reference\n2026-09-01,Vendor,12.34,A1\n2026-09-02,Credit,,A2\n",
        "2026-09",
    )
    assert rows[0]["amount_cents"] == 1234
    assert skipped == 1

    rows, skipped = parse_statement_csv(
        b"Date,Description,Amount,Type\n2026-09-01,Vendor,-9.90,\n2026-09-02,Refund,4.00,credit\n",
        "2026-09",
    )
    assert [row["amount_cents"] for row in rows] == [990]
    assert skipped == 1


def test_statement_upload_reconciliation_payment_audit_and_export(monkeypatch, tmp_path: Path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    store = ReceiptStore(get_settings().database_path)
    matched_id = accepted(store, "Acme Maintenance", 120.00, "2026-09-03")
    unmatched_id = accepted(store, "Beta Supplies", 80.00, "2026-09-05")
    csv_content = (
        b"Date,Description,Debit,Reference\n"
        b"2026-09-04,ACME MAINTENANCE,120.00,T1\n"
        b"2026-09-07,Unknown merchant,44.00,T2\n"
        b"2026-09-07,Unknown merchant,44.00,T3\n"
    )

    assert client.post("/bank-statements/upload", files={"statement": ("month.csv", csv_content, "text/csv")},
                       data={"statement_month": "2026-09", "currency": "SGD", "account_label": "Operating"}).status_code == 401
    response = client.post(
        "/bank-statements/upload", headers=HEADERS,
        files={"statement": ("month.csv", csv_content, "text/csv")},
        data={"statement_month": "2026-09", "currency": "SGD", "account_label": "Operating"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["transactions_imported"] == 3
    source = client.get(
        f"/bank-statements/{response.json()['statement_id']}/source", headers=HEADERS
    )
    assert source.content == csv_content
    assert source.headers["cache-control"] == "no-store"
    duplicate = client.post(
        "/bank-statements/upload", headers=HEADERS,
        files={"statement": ("month.csv", csv_content, "text/csv")},
        data={"statement_month": "2026-09", "currency": "SGD", "account_label": "Operating"},
    )
    assert duplicate.status_code == 409

    data = client.get("/reconciliation?month=2026-09&currency=SGD", headers=HEADERS).json()
    assert data["totals"] == {
        "bank_debits_cents": 20800,
        "receipt_spend_cents": 20000,
        "matched_cents": 12000,
        "difference_cents": 800,
        "exception_count": 3,
    }
    assert next(item for item in data["receipts"] if item["receipt_id"] == matched_id)["status"] == "PAID"
    assert {item["status"] for item in data["transactions"]} == {"MATCHED", "DUPLICATE_TRANSACTION"}

    update = client.post(
        f"/receipts/{unmatched_id}/payment-state", headers=HEADERS,
        json={"state": "PAYMENT_ISSUE", "actor": "Finance reviewer", "note": "Bank transfer was rejected"},
    )
    assert update.status_code == 200
    refreshed = monthly_reconciliation(store, "2026-09", "SGD")
    row = next(item for item in refreshed["receipts"] if item["receipt_id"] == unmatched_id)
    assert row["status"] == "PAYMENT_ISSUE"
    assert row["payment_event"]["actor"] == "Finance reviewer"

    workbook = build_monthly_export(store, "2026-09", "SGD")
    assert workbook.startswith(b"PK")
    exported = client.post("/reconciliation/export", headers=HEADERS,
                           json={"month": "2026-09", "currency": "SGD"})
    assert exported.status_code == 200
    assert "ledgerly-reconciliation-2026-09-SGD.xlsx" in exported.headers["content-disposition"]
