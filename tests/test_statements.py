from pathlib import Path
from uuid import uuid4
from io import BytesIO
from decimal import Decimal
from zipfile import ZipFile
from xml.etree import ElementTree

from app.database import ReceiptStore
from app.main import get_settings, get_statement_extractor
from app.ocr import OCRResult
from app.statement_extraction import (
    StatementExtraction,
    deterministic_statement_extract,
    redact_statement_text_for_ai,
)
from app.statements import (
    build_monthly_export,
    create_preview_token,
    monthly_reconciliation,
    import_statement,
    parse_statement_csv,
    statement_preview,
    verify_preview_token,
)
from test_api import TEST_KEY, configured_client
from xlsx_assertions import sheet_cells


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


def test_period_overview_includes_receipts_without_statements_and_review_goes_stale(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    store = ReceiptStore(get_settings().database_path)
    accepted(store, "August supplier", 15.00, "2026-08-27")
    accepted(store, "September supplier", 40.00, "2026-09-05")
    periods = client.get("/bank-statements/periods", headers=HEADERS).json()["items"]
    assert [(row["month"], row["statement_count"], row["receipt_count"])
            for row in periods] == [("2026-09", 0, 1), ("2026-08", 0, 1)]
    assert periods[0]["review"]["status"] == "not_reviewed"

    source = b"Date,Description,Debit\n2026-09-05,September supplier,40.00\n"
    uploaded = client.post("/bank-statements/upload", headers=HEADERS,
                           files={"statement": ("sept.csv", source, "text/csv")},
                           data={"statement_month": "2026-09", "currency": "SGD", "account_label": "Operating"})
    assert uploaded.status_code == 200, uploaded.text
    month = client.get("/reconciliation?month=2026-09&currency=SGD", headers=HEADERS).json()
    assert month["review"]["status"] == "not_reviewed"
    body = {"month": "2026-09", "currency": "SGD", "actor": "Finance reviewer",
            "note": "Checked original bank source and September receipts",
            "fingerprint": month["review"]["fingerprint"]}
    assert client.post("/reconciliation/reviews", json=body).status_code == 401
    reviewed = client.post("/reconciliation/reviews", headers=HEADERS, json=body)
    assert reviewed.status_code == 200, reviewed.text
    assert client.get("/reconciliation?month=2026-09&currency=SGD", headers=HEADERS).json()["review"]["status"] == "reviewed"
    accepted(store, "Another September supplier", 5.00, "2026-09-20")
    stale = client.get("/reconciliation?month=2026-09&currency=SGD", headers=HEADERS).json()
    assert stale["review"]["status"] == "outdated"
    assert client.post("/reconciliation/reviews", headers=HEADERS, json=body).status_code == 422
    assert client.get("/bank-statements/periods", headers=HEADERS).json()["items"][0]["review"]["status"] == "outdated"
    review_summary = sheet_cells(build_monthly_export(store, "2026-09", "SGD"), 1)
    assert review_summary["H11"] == "Outdated"
    assert review_summary["H12"] == "Finance reviewer"
    assert review_summary["H14"] == "Checked original bank source and September receipts"


def test_adjacent_month_candidate_does_not_change_paid_status(monkeypatch, tmp_path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    store = ReceiptStore(get_settings().database_path)
    receipt_id = accepted(store, "Boundary Supplier", 22.00, "2026-08-30")
    source = b"Date,Description,Debit\n2026-09-02,BOUNDARY SUPPLIER,22.00\n"
    assert client.post("/bank-statements/upload", headers=HEADERS,
                       files={"statement": ("sept.csv", source, "text/csv")},
                       data={"statement_month": "2026-09", "currency": "SGD", "account_label": "Operating"}).status_code == 200
    august = client.get("/reconciliation?month=2026-08&currency=SGD", headers=HEADERS).json()
    september = client.get("/reconciliation?month=2026-09&currency=SGD", headers=HEADERS).json()
    assert august["receipts"][0]["receipt_id"] == receipt_id
    assert august["receipts"][0]["status"] == "NO_BANK_MATCH"
    assert august["receipts"][0]["adjacent_month_candidate"]["month"] == "2026-09"
    assert september["transactions"][0]["status"] == "MISSING_RECEIPT"
    assert september["transactions"][0]["adjacent_month_candidate"] == {"month": "2026-08", "receipt_id": receipt_id}
    assert september["totals"]["matched_cents"] == 0
    workbook = build_monthly_export(store, "2026-09", "SGD")
    assert sheet_cells(workbook, 1)["B17"] == "N/A — no accepted spend"
    assert receipt_id in sheet_cells(workbook, 2)["J6"]


def test_duplicate_bank_debits_cannot_count_as_suggested_matches(tmp_path):
    store = ReceiptStore(tmp_path / "expenses.db")
    receipt_id = accepted(store, "Acme", 10.00, "2026-09-01")
    import_statement(
        store,
        b"Date,Description,Debit,Reference\n"
        b"2026-09-01,ACME,10.00,D1\n"
        b"2026-09-01,ACME,10.00,D2\n",
        "dupes.csv", "2026-09", "SGD", "Operating",
    )
    data = monthly_reconciliation(store, "2026-09", "SGD")
    assert data["totals"]["matched_cents"] == 0
    assert data["receipts"][0]["receipt_id"] == receipt_id
    assert data["receipts"][0]["status"] == "NO_BANK_MATCH"
    assert all(item["status"] == "DUPLICATE_TRANSACTION" and item["receipt_id"] is None
               for item in data["transactions"])
    summary = sheet_cells(build_monthly_export(store, "2026-09", "SGD"), 1)
    assert summary["D7"] == 0


def statement_text() -> str:
    def row(day: str, description: str, debit: str = "", credit: str = "", balance: str = "") -> str:
        return f"{day:<12}{description:<30}{debit:<15}{credit:<15}{balance}"

    return "\n".join([
        "OCBC BUSINESS ACCOUNT STATEMENT CURRENCY SGD",
        "Account Number: 123-456-4321",
        "Opening balance 1,000.00",
        row("Date", "Description", "Debit", "Credit", "Balance"),
        row("01/09/2026", "ACME MAINTENANCE", "120.00", "", "880.00"),
        row("02/09/2026", "CUSTOMER PAYMENT", "", "50.00", "930.00"),
        "Closing balance 930.00",
    ])


def test_statement_pdf_text_is_private_first_and_balance_checked():
    extracted = deterministic_statement_extract(statement_text(), "2026-09")
    preview = statement_preview(
        extracted, "2026-09", "SGD", "Operating", "deterministic", "pdf:native"
    )

    assert extracted.bank_name == "OCBC"
    assert extracted.account_last_four == "4321"
    assert preview["transactions_imported"] == 1
    assert preview["transactions"][0]["description"] == "ACME MAINTENANCE"
    assert preview["transactions"][0]["amount_cents"] == 12000
    assert preview["validation"]["credits_skipped"] == 1
    assert preview["validation"]["credit_total_cents"] == 5000
    assert preview["validation"]["calculated_closing_balance_cents"] == 93000
    assert preview["validation"]["balance_difference_cents"] == 0
    assert preview["validation"]["balance_reconciled"] is True
    assert preview["validation"]["confirmable"] is True

    mismatch = extracted.model_copy(update={"closing_balance": extracted.opening_balance})
    blocked = statement_preview(
        mismatch, "2026-09", "SGD", "Operating", "deterministic", "pdf:native"
    )
    assert blocked["validation"]["balance_reconciled"] is False
    assert blocked["validation"]["balance_difference_cents"] == -7000
    assert blocked["validation"]["confirmable"] is False


def test_statement_confirmation_token_binds_file_and_preview():
    preview = {"statement_month": "2026-09", "transactions": [{"amount_cents": 12000}]}
    token = create_preview_token(TEST_KEY, b"%PDF-original", preview)
    verify_preview_token(TEST_KEY, token, b"%PDF-original", preview)

    tampered = {"statement_month": "2026-09", "transactions": [{"amount_cents": 1}]}
    try:
        verify_preview_token(TEST_KEY, token, b"%PDF-original", tampered)
    except ValueError as exc:
        assert "preview" in str(exc).lower()
    else:
        raise AssertionError("Tampered preview was accepted")


def test_ai_input_masks_obvious_account_numbers():
    redacted = redact_statement_text_for_ai(
        "Account Number: 123-456-7890\nFAST PAYMENT TO ACME 120.00"
    )
    assert "123-456-7890" not in redacted
    assert "•••• 7890" in redacted
    assert "FAST PAYMENT TO ACME 120.00" in redacted


def test_pdf_statement_preview_confirm_retains_exact_source(monkeypatch, tmp_path: Path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    content = b"%PDF-synthetic-statement"
    monkeypatch.setattr(
        "app.main.extract_pdf_text",
        lambda *args, **kwargs: OCRResult(
            text=statement_text(), engine="pdf:native", confidence=None
        ),
    )
    form = {"statement_month": "2026-09", "currency": "SGD", "account_label": "Operating"}
    response = client.post(
        "/bank-statements/preview", headers=HEADERS,
        files={"statement": ("ocbc-september.pdf", content, "application/pdf")},
        data=form,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["preview"]["validation"]["balance_reconciled"] is True
    assert result["preview"]["extraction_method"] == "deterministic"

    confirm = client.post(
        "/bank-statements/confirm", headers=HEADERS,
        files={"statement": ("ocbc-september.pdf", content, "application/pdf")},
        data={
            "preview_json": __import__("json").dumps(result["preview"]),
            "confirmation_token": result["confirmation_token"],
            "evidence_confirmed": "true",
        },
    )
    assert confirm.status_code == 200, confirm.text
    statement_id = confirm.json()["statement_id"]
    source = client.get(f"/bank-statements/{statement_id}/source", headers=HEADERS)
    assert source.headers["content-type"] == "application/pdf"
    assert source.content == content

    preview_png = b"\\x89PNG\\r\\n\\x1a\\nrendered"
    monkeypatch.setattr(
        "app.main.render_pdf_first_page",
        lambda *args, **kwargs: preview_png,
    )
    source_preview = client.get(
        f"/bank-statements/{statement_id}/source-preview", headers=HEADERS
    )
    assert source_preview.status_code == 200
    assert source_preview.headers["content-type"] == "image/png"
    assert source_preview.content == preview_png

    replay = client.post(
        "/bank-statements/confirm", headers=HEADERS,
        files={"statement": ("ocbc-september.pdf", content, "application/pdf")},
        data={
            "preview_json": __import__("json").dumps(result["preview"]),
            "confirmation_token": result["confirmation_token"],
            "evidence_confirmed": "true",
        },
    )
    assert replay.status_code == 409


def test_pdf_statement_ai_fallback_is_explicit_opt_in(monkeypatch, tmp_path: Path):
    client, *_ = configured_client(monkeypatch, tmp_path)
    content = b"%PDF-unfamiliar-layout"
    monkeypatch.setattr(
        "app.main.extract_pdf_text",
        lambda *args, **kwargs: OCRResult(
            text="UNFAMILIAR STATEMENT LAYOUT", engine="pdf:native", confidence=None
        ),
    )

    class StubStatementExtractor:
        def __init__(self):
            self.inputs = []

        async def extract(self, text):
            self.inputs.append(text)
            return StatementExtraction.model_validate({
                "bank_name": "OCBC", "account_last_four": "4321",
                "currency": "SGD", "opening_balance": 1000, "closing_balance": 880,
                "transactions": [{"posted_date": "2026-09-01", "description": "ACME",
                                  "debit_amount": 120, "credit_amount": None, "balance": 880,
                                  "reference": None}],
                "needs_review": True, "review_reasons": ["AI fallback used"],
            })

    extractor = StubStatementExtractor()
    client.app.dependency_overrides[get_statement_extractor] = lambda: extractor
    request = {
        "files": {"statement": ("month.pdf", content, "application/pdf")},
        "data": {"statement_month": "2026-09", "currency": "SGD",
                 "account_label": "Operating"},
        "headers": HEADERS,
    }
    private_attempt = client.post("/bank-statements/preview", **request)
    assert private_attempt.status_code == 422
    assert extractor.inputs == []

    request["data"]["allow_ai"] = "true"
    opted_in = client.post("/bank-statements/preview", **request)
    assert opted_in.status_code == 200, opted_in.text
    assert opted_in.json()["preview"]["extraction_method"] == "ai"
    assert extractor.inputs == ["UNFAMILIAR STATEMENT LAYOUT"]

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
    assert {item["statement_id"] for item in data["transactions"]} == {response.json()["statement_id"]}

    update = client.post(
        f"/receipts/{unmatched_id}/payment-state", headers=HEADERS,
        json={"state": "PAYMENT_ISSUE", "actor": "Finance reviewer", "note": "Bank transfer was rejected"},
    )
    assert update.status_code == 200
    refreshed = monthly_reconciliation(store, "2026-09", "SGD")
    row = next(item for item in refreshed["receipts"] if item["receipt_id"] == unmatched_id)
    assert row["status"] == "PAYMENT_ISSUE"
    assert row["payment_event"]["actor"] == "Finance reviewer"

    payable = client.post(
        f"/receipts/{unmatched_id}/payment-state", headers=HEADERS,
        json={"state": "TRADE_PAYABLE", "actor": "Finance reviewer",
              "note": "Invoice checked, payment planned after approval",
              "invoice_due_date": "2026-09-30", "planned_payment_date": "2026-09-28",
              "expected_version": 1},
    )
    assert payable.status_code == 200, payable.text
    assert payable.json()["invoice_due_date"] == "2026-09-30"
    assert payable.json()["previous_state"] == "PAYMENT_ISSUE"
    assert client.post(
        f"/receipts/{unmatched_id}/payment-state", headers=HEADERS,
        json={"state": "CLEAR", "actor": "Finance reviewer",
              "note": "Cannot clear with a payable date", "invoice_due_date": "2026-10-01"},
    ).status_code == 422
    stale = client.post(
        f"/receipts/{unmatched_id}/payment-state", headers=HEADERS,
        json={"state": "CLEAR", "actor": "Finance reviewer",
              "note": "Payment was checked with the bank", "expected_version": 1},
    )
    assert stale.status_code == 422
    latest = client.get("/reconciliation?month=2026-09&currency=SGD", headers=HEADERS).json()
    updated_row = next(item for item in latest["receipts"] if item["receipt_id"] == unmatched_id)
    assert updated_row["status"] == "TRADE_PAYABLE"
    assert [event["version"] for event in updated_row["payment_events"]] == [2, 1]
    detail = client.get(f"/receipts/{unmatched_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert [event["version"] for event in detail.json()["payment_events"]] == [2, 1]

    workbook = build_monthly_export(store, "2026-09", "SGD")
    assert workbook.startswith(b"PK")
    with ZipFile(BytesIO(workbook)) as archive:
        names = archive.namelist()
        workbook_xml = archive.read("xl/workbook.xml").decode()
        strings = archive.read("xl/sharedStrings.xml").decode()
        summary_xml = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    widths = {int(column.get("min")): float(column.get("width"))
              for column in summary_xml.find(f"{ns}cols")}
    assert widths[1] >= 39  # The full "Bank debits minus accepted receipts" label.
    assert widths[3] >= 21  # The formatted SGD accepted-receipts KPI, not ###.
    assert all(name in workbook_xml for name in (
        "Summary", "Bank transactions", "Receipts", "Statement sources", "Payment audit"
    ))
    assert all(value in strings for value in (
        "Bank debits minus accepted receipts", "Spend by category", "Total bank debits",
        "Total accepted receipts", "Retained statement sources", "Suggested matched receipt spend",
    ))
    assert any(name.startswith("xl/tables/table") for name in names)
    summary = sheet_cells(workbook, 1)
    assert summary["C7"] == 200
    assert (summary["B12"], summary["B13"], summary["B14"], summary["B15"], summary["B17"]) == (
        208, 200, 120, 8, Decimal("0.6"),
    )
    assert summary["H11"] == "Not Reviewed"
    bank = sheet_cells(workbook, 2)
    assert bank["C6"] == 120
    assert bank["H6"] == "month.csv"
    assert bank["I6"] == response.json()["statement_id"]
    receipts = sheet_cells(workbook, 3)
    assert receipts["E6"] == "SUGGESTED_BANK_MATCH"
    assert receipts["I7"] == "2026-09-30"
    assert receipts["J7"] == "2026-09-28"
    assert sheet_cells(workbook, 4)["A6"] == response.json()["statement_id"]
    payment_audit = sheet_cells(workbook, 5)
    assert (payment_audit["D6"], payment_audit["D7"], payment_audit["H7"], payment_audit["I7"]) == (
        "PAYMENT_ISSUE", "TRADE_PAYABLE", "2026-09-30", "2026-09-28",
    )
    exported = client.post("/reconciliation/export", headers=HEADERS,
                           json={"month": "2026-09", "currency": "SGD"})
    assert exported.status_code == 200
    assert "ledgerly-reconciliation-2026-09-SGD.xlsx" in exported.headers["content-disposition"]


def test_monthly_export_keeps_untrusted_bank_text_inert(tmp_path: Path):
    store = ReceiptStore(tmp_path / "expenses.db")
    import_statement(
        store,
        b"Date,Description,Debit\n2026-09-01,=2+2,10.00\n",
        "statement.csv",
        "2026-09",
        "SGD",
        "Operating",
    )
    workbook = build_monthly_export(store, "2026-09", "SGD")
    with ZipFile(BytesIO(workbook)) as archive:
        sheet_xml = b"".join(
            archive.read(name) for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet")
        )
        strings = archive.read("xl/sharedStrings.xml")
    assert b"<f>" not in sheet_xml
    assert b"=2+2" in strings


def test_statement_removal_restore_preserves_evidence_and_receipts(monkeypatch, tmp_path):
    import json
    client, *_ = configured_client(monkeypatch, tmp_path)
    store = ReceiptStore(get_settings().database_path)
    receipt_id = accepted(store, "Acme", 12.00, "2026-09-01")
    content = b"Date,Description,Debit\n2026-09-01,Acme,12.00\n"
    result = import_statement(store, content, "wrong.csv", "2026-09", "SGD", "Operating")
    statement_id = result["statement_id"]
    endpoint = f"/bank-statements/{statement_id}/lifecycle"
    body = {"action": "REMOVE", "actor": "Finance reviewer", "reason": "Wrong source uploaded"}
    assert client.post(endpoint, json=body).status_code == 401
    assert client.post(endpoint, headers=HEADERS, json={**body, "reason": "     "}).status_code == 422
    assert monthly_reconciliation(store, "2026-09", "SGD")["totals"]["matched_cents"] == 1200
    assert client.post(endpoint, headers=HEADERS, json=body).status_code == 200
    assert client.post(endpoint, headers=HEADERS, json=body).status_code == 409
    removed = monthly_reconciliation(store, "2026-09", "SGD")
    assert removed["statements"] == []
    assert removed["transactions"] == []
    assert removed["totals"]["bank_debits_cents"] == 0
    assert removed["totals"]["matched_cents"] == 0
    assert removed["totals"]["receipt_spend_cents"] == 1200
    assert removed["receipts"][0]["receipt_id"] == receipt_id
    assert removed["receipts"][0]["status"] == "NO_BANK_MATCH"
    assert removed["removed_statements"][0]["statement_id"] == statement_id
    periods = client.get("/bank-statements/periods", headers=HEADERS).json()["items"]
    assert periods[0]["transaction_count"] == 0
    assert client.get(f"/bank-statements/{statement_id}/source", headers=HEADERS).content == content
    assert client.post(endpoint, headers=HEADERS, json={**body, "action": "RESTORE"}).status_code == 200
    restored = monthly_reconciliation(store, "2026-09", "SGD")
    assert restored["totals"]["matched_cents"] == 1200
    assert restored["removed_statements"] == []
    events = json.loads(restored["statements"][0]["metadata_json"])["lifecycle_events"]
    assert [event["action"] for event in events] == ["REMOVE", "RESTORE"]
    assert client.post(f"/bank-statements/{uuid4()}/lifecycle", headers=HEADERS, json=body).status_code == 404
