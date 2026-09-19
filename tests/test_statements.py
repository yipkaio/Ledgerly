from pathlib import Path
from uuid import uuid4
from io import BytesIO
from zipfile import ZipFile

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
    assert preview["validation"]["balance_reconciled"] is True
    assert preview["validation"]["confirmable"] is True

    mismatch = extracted.model_copy(update={"closing_balance": extracted.opening_balance})
    blocked = statement_preview(
        mismatch, "2026-09", "SGD", "Operating", "deterministic", "pdf:native"
    )
    assert blocked["validation"]["balance_reconciled"] is False
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
