"""Monthly bank-statement ingestion and evidence-led receipt reconciliation."""

from __future__ import annotations

import csv
import base64
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import hmac
import io
import json
import re
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.statement_extraction import StatementExtraction


STATEMENT_SCHEMA = (
    "CREATE TABLE bank_statements (statement_id TEXT PRIMARY KEY, statement_month TEXT NOT NULL, "
    "currency TEXT NOT NULL, account_label TEXT NOT NULL, original_filename TEXT NOT NULL, "
    "content_sha256 TEXT NOT NULL UNIQUE, source_csv BLOB NOT NULL, uploaded_at TEXT NOT NULL, row_count INTEGER NOT NULL, "
    "skipped_rows INTEGER NOT NULL)",
    "CREATE TABLE bank_transactions (transaction_id TEXT PRIMARY KEY, statement_id TEXT NOT NULL "
    "REFERENCES bank_statements(statement_id) ON DELETE CASCADE, posted_date TEXT NOT NULL, "
    "description TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0), "
    "reference TEXT, source_row INTEGER NOT NULL)",
    "CREATE INDEX bank_transaction_statement ON bank_transactions(statement_id, posted_date)",
    "CREATE TABLE receipt_payment_events (receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id), "
    "version INTEGER NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(receipt_id, version))",
)

STATEMENT_MIGRATION_8 = (
    "ALTER TABLE bank_statements ADD COLUMN source_media_type TEXT NOT NULL DEFAULT 'text/csv'",
    "ALTER TABLE bank_statements ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'csv'",
    "ALTER TABLE bank_statements ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE bank_statements ADD COLUMN validation_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE bank_statements ADD COLUMN imported_by TEXT NOT NULL DEFAULT 'Legacy import'",
)

STATEMENT_MIGRATION_9 = (
    "CREATE TABLE monthly_close_reviews (id INTEGER PRIMARY KEY, month TEXT NOT NULL, "
    "currency TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL, "
    "reviewed_at TEXT NOT NULL, fingerprint TEXT NOT NULL)",
    "CREATE INDEX monthly_close_review_period ON monthly_close_reviews(month,currency,id DESC)",
)

PREVIEW_TTL_SECONDS = 30 * 60


class StatementInvalid(ValueError):
    """The uploaded statement cannot be safely normalized."""


class StatementDuplicate(ValueError):
    """The exact statement file has already been imported."""

    def __init__(self, statement_id: str):
        super().__init__("This exact bank statement was already uploaded. If removed, restore it from Removed statements in its original month.")
        self.statement_id = statement_id


class PaymentUpdate(BaseModel):
    state: str
    actor: str = Field(min_length=2, max_length=100)
    note: str = Field(min_length=5, max_length=500)
    invoice_due_date: date | None = None
    planned_payment_date: date | None = None
    expected_version: int | None = Field(default=None, ge=0)

    @field_validator("actor", "note", mode="before")
    @classmethod
    def strip_payment_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("state")
    @classmethod
    def supported_state(cls, value: str) -> str:
        if value not in {"TRADE_PAYABLE", "PAYMENT_ISSUE", "CLEAR"}:
            raise ValueError("Unsupported payment state")
        return value

    @model_validator(mode="after")
    def dates_belong_to_payable(self):
        if self.state != "TRADE_PAYABLE" and (self.invoice_due_date or self.planned_payment_date):
            raise ValueError("Payable dates can only be recorded with Trade payable")
        return self


class StatementLifecycleRequest(BaseModel):
    action: str = Field(pattern="^(REMOVE|RESTORE)$")
    actor: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("actor", "reason", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


def change_statement_state(store, statement_id: str, body: StatementLifecycleRequest) -> dict:
    """Reversible exclusion, preserving source, debits and an append-only event list."""
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT metadata_json FROM bank_statements WHERE statement_id=?",
                         (statement_id,)).fetchone()
        if row is None:
            raise StatementInvalid("Bank statement was not found")
        metadata = json.loads(row[0])
        removed = metadata.get("removed", False)
        wanted = body.action == "REMOVE"
        if removed == wanted:
            raise StatementInvalid("Statement is already removed" if wanted else "Statement is already active")
        event = {"action": body.action, "actor": body.actor, "reason": body.reason,
                 "occurred_at": datetime.now(timezone.utc).isoformat()}
        metadata.setdefault("lifecycle_events", []).append(event)
        metadata["removed"] = wanted
        db.execute("UPDATE bank_statements SET metadata_json=? WHERE statement_id=?",
                   (json.dumps(metadata, allow_nan=False), statement_id))
    return {"statement_id": statement_id, "removed": wanted, "event": event}


class MonthlyExportRequest(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class MonthReviewRequest(MonthlyExportRequest):
    actor: str = Field(min_length=2, max_length=100)
    note: str = Field(min_length=5, max_length=500)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("actor", "note", mode="before")
    @classmethod
    def strip_review(cls, value):
        return value.strip() if isinstance(value, str) else value


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _pick(headers: dict[str, str], *names: str) -> str | None:
    for name in names:
        if name in headers:
            return headers[name]
    return None


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise StatementInvalid(f"Unrecognised transaction date: {value[:24]}")


def _money(value: str) -> int:
    cleaned = value.strip().replace(",", "").replace("$", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise StatementInvalid("A transaction amount is invalid") from exc
    if not amount.is_finite():
        raise StatementInvalid("A transaction amount is invalid")
    if negative:
        amount = -amount
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_statement_csv(content: bytes, statement_month: str) -> tuple[list[dict], int]:
    if len(content) > 2 * 1024 * 1024:
        raise StatementInvalid("Bank statement CSV must be 2 MB or smaller")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StatementInvalid("Bank statement CSV must use UTF-8 encoding") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise StatementInvalid("Bank statement CSV has no header row")
    headers = {_header(name): name for name in reader.fieldnames if name}
    date_key = _pick(headers, "date", "transactiondate", "postingdate", "valuedate")
    description_key = _pick(headers, "description", "details", "narrative", "merchant", "payee")
    debit_key = _pick(headers, "debit", "withdrawal", "moneyout", "debitamount")
    amount_key = _pick(headers, "amount", "transactionamount")
    reference_key = _pick(headers, "reference", "transactionid", "ref", "chequenumber")
    type_key = _pick(headers, "type", "transactiontype", "direction")
    if not date_key or not description_key or not (debit_key or amount_key):
        raise StatementInvalid("CSV needs Date, Description, and Debit (or Amount) columns")
    transactions: list[dict] = []
    skipped = 0
    for row_number, row in enumerate(reader, start=2):
        if row_number > 5001:
            raise StatementInvalid("Bank statement CSV is limited to 5,000 rows")
        if not any((value or "").strip() for value in row.values()):
            continue
        posted = _parse_date(row.get(date_key, ""))
        raw = row.get(debit_key, "") if debit_key else row.get(amount_key, "")
        if not raw.strip():
            skipped += 1
            continue
        cents = _money(raw)
        kind = (row.get(type_key, "") if type_key else "").strip().lower()
        if debit_key:
            is_debit = cents != 0
        elif kind:
            is_debit = kind in {"debit", "withdrawal", "payment", "purchase", "dr"}
        else:
            # Signed bank exports conventionally represent money out as negative.
            is_debit = cents < 0
        if not is_debit or cents == 0:
            skipped += 1
            continue
        description = " ".join((row.get(description_key, "") or "").split())
        if not description:
            raise StatementInvalid(f"Transaction row {row_number} has no description")
        transactions.append({
            "transaction_id": str(uuid4()),
            "posted_date": posted.isoformat(),
            "description": description[:300],
            "amount_cents": abs(cents),
            "reference": ((row.get(reference_key, "") or "").strip()[:100] if reference_key else None),
            "source_row": row_number,
            "outside_month": posted.strftime("%Y-%m") != statement_month,
        })
    if not transactions:
        raise StatementInvalid("No debit transactions were found in the CSV")
    return transactions, skipped


def import_statement(store, content: bytes, filename: str, statement_month: str,
                     currency: str, account_label: str,
                     imported_by: str = "Shared workspace user") -> dict:
    if len(account_label.strip()) < 2:
        raise StatementInvalid("Account label must contain at least two visible characters")
    if len(imported_by.strip()) < 2:
        raise StatementInvalid("Importer name must contain at least two visible characters")
    transactions, skipped = parse_statement_csv(content, statement_month)
    digest = hashlib.sha256(content).hexdigest()
    statement_id = str(uuid4())
    uploaded_at = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        duplicate = db.execute(
            "SELECT statement_id FROM bank_statements WHERE content_sha256=?", (digest,)
        ).fetchone()
        if duplicate:
            raise StatementDuplicate(duplicate[0])
        db.execute(
            "INSERT INTO bank_statements (statement_id,statement_month,currency,account_label,"
            "original_filename,content_sha256,source_csv,uploaded_at,row_count,skipped_rows,"
            "source_media_type,extraction_method,metadata_json,validation_json,imported_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (statement_id, statement_month, currency, account_label.strip(), filename[:200],
             digest, content, uploaded_at, len(transactions), skipped, "text/csv", "csv",
             "{}", json.dumps({"preview_confirmed": False, "balance_reconciled": None}),
             imported_by.strip()),
        )
        db.executemany(
            "INSERT INTO bank_transactions VALUES (?,?,?,?,?,?,?)",
            [(item["transaction_id"], statement_id, item["posted_date"], item["description"],
              item["amount_cents"], item["reference"], item["source_row"])
             for item in transactions],
        )
    return {"statement_id": statement_id, "month": statement_month, "currency": currency,
            "transactions_imported": len(transactions), "rows_skipped": skipped,
            "outside_month": sum(1 for item in transactions if item["outside_month"])}


def _cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def statement_preview(extraction: StatementExtraction, statement_month: str,
                      declared_currency: str, account_label: str,
                      extraction_method: str, text_engine: str,
                      imported_by: str = "Shared workspace user") -> dict:
    if len(account_label.strip()) < 2:
        raise StatementInvalid("Account label must contain at least two visible characters")
    if len(imported_by.strip()) < 2:
        raise StatementInvalid("Importer name must contain at least two visible characters")
    if extraction.currency and extraction.currency != declared_currency:
        raise StatementInvalid(
            f"The statement appears to be {extraction.currency}, not {declared_currency}"
        )
    transactions = []
    credit_count = 0
    credit_total_cents = 0
    net_cents = 0
    for source_row, item in enumerate(extraction.transactions, start=1):
        debit = _cents(item.debit_amount) or 0
        credit = _cents(item.credit_amount) or 0
        net_cents += credit - debit
        if debit <= 0:
            credit_count += 1
            credit_total_cents += credit
            continue
        transactions.append({
            "posted_date": item.posted_date.isoformat(),
            "description": " ".join(item.description.split())[:300],
            "amount_cents": debit,
            "reference": item.reference[:100] if item.reference else None,
            "source_row": source_row,
            "outside_month": item.posted_date.strftime("%Y-%m") != statement_month,
        })
    if not transactions:
        raise StatementInvalid("No debit transactions were found in the statement")

    opening = _cents(extraction.opening_balance)
    closing = _cents(extraction.closing_balance)
    reconciled: bool | None = None
    if opening is not None and closing is not None:
        reconciled = abs((opening + net_cents) - closing) <= 2

    outside = sum(1 for item in transactions if item["outside_month"])
    if outside == len(transactions):
        raise StatementInvalid(
            f"Every extracted debit falls outside the selected month {statement_month}"
        )
    warnings = list(dict.fromkeys(extraction.review_reasons))
    if outside:
        warnings.append(f"{outside} debit transaction(s) fall outside {statement_month}")
    if opening is None or closing is None:
        warnings.append("Opening or closing balance was not available for an arithmetic cross-check")
    elif reconciled is False:
        warnings.append("Opening balance plus credits less debits does not equal closing balance")
    if extraction_method == "ai":
        warnings.append("AI fallback was used; verify every row against the original statement")

    metadata = {
        "bank_name": extraction.bank_name,
        "account_last_four": extraction.account_last_four,
        "opening_balance_cents": opening,
        "closing_balance_cents": closing,
        "statement_start": extraction.statement_start.isoformat() if extraction.statement_start else None,
        "statement_end": extraction.statement_end.isoformat() if extraction.statement_end else None,
    }
    return {
        "statement_month": statement_month,
        "currency": declared_currency,
        "account_label": account_label.strip(),
        "imported_by": imported_by.strip(),
        "extraction_method": extraction_method,
        "text_engine": text_engine,
        "metadata": metadata,
        "validation": {
            "balance_reconciled": reconciled,
            "confirmable": reconciled is not False,
            "credit_total_cents": credit_total_cents,
            "calculated_closing_balance_cents": opening + net_cents if opening is not None else None,
            "balance_difference_cents": opening + net_cents - closing if opening is not None and closing is not None else None,
            "warnings": warnings,
            "credits_skipped": credit_count,
            "outside_month": outside,
        },
        "transactions": transactions,
        "transactions_imported": len(transactions),
        "debit_total_cents": sum(item["amount_cents"] for item in transactions),
    }


def _preview_bytes(preview: dict) -> bytes:
    return json.dumps(preview, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def create_preview_token(secret: str, content: bytes, preview: dict) -> str:
    payload = {
        "exp": int(datetime.now(timezone.utc).timestamp()) + PREVIEW_TTL_SECONDS,
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "preview_sha256": hashlib.sha256(_preview_bytes(preview)).hexdigest(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def verify_preview_token(secret: str, token: str, content: bytes, preview: dict) -> None:
    try:
        encoded_text, signature_text = token.split(".", 1)
        encoded = encoded_text.encode("ascii")
        supplied = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        expected = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        raw = base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4))
        payload = json.loads(raw)
        if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            raise StatementInvalid("Statement preview expired; preview the file again")
        if not hmac.compare_digest(payload["file_sha256"], hashlib.sha256(content).hexdigest()):
            raise ValueError
        preview_hash = hashlib.sha256(_preview_bytes(preview)).hexdigest()
        if not hmac.compare_digest(payload["preview_sha256"], preview_hash):
            raise ValueError
    except StatementInvalid:
        raise
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
        raise StatementInvalid("Statement confirmation is invalid; preview the file again") from exc


def import_previewed_statement(store, content: bytes, filename: str, media_type: str,
                               preview: dict) -> dict:
    validation = preview.get("validation") or {}
    if validation.get("confirmable") is not True:
        raise StatementInvalid("This statement cannot be imported until its balances reconcile")
    transactions = preview.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise StatementInvalid("Statement preview contains no debit transactions")
    digest = hashlib.sha256(content).hexdigest()
    statement_id = str(uuid4())
    uploaded_at = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        duplicate = db.execute(
            "SELECT statement_id FROM bank_statements WHERE content_sha256=?", (digest,)
        ).fetchone()
        if duplicate:
            raise StatementDuplicate(duplicate[0])
        db.execute(
            "INSERT INTO bank_statements (statement_id,statement_month,currency,account_label,"
            "original_filename,content_sha256,source_csv,uploaded_at,row_count,skipped_rows,"
            "source_media_type,extraction_method,metadata_json,validation_json,imported_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (statement_id, preview["statement_month"], preview["currency"],
             preview["account_label"], filename[:200], digest, content, uploaded_at,
             len(transactions), int(validation.get("credits_skipped", 0)), media_type,
             preview.get("extraction_method", "unknown"),
             json.dumps({**(preview.get("metadata") or {}),
                         "text_engine": preview.get("text_engine")}, allow_nan=False),
             json.dumps({**validation, "preview_confirmed": True}, allow_nan=False),
             preview["imported_by"]),
        )
        db.executemany(
            "INSERT INTO bank_transactions VALUES (?,?,?,?,?,?,?)",
            [(str(uuid4()), statement_id, item["posted_date"], item["description"],
              int(item["amount_cents"]), item.get("reference"), int(item["source_row"]))
             for item in transactions],
        )
    return {
        "statement_id": statement_id,
        "month": preview["statement_month"],
        "currency": preview["currency"],
        "transactions_imported": len(transactions),
        "rows_skipped": int(validation.get("credits_skipped", 0)),
        "outside_month": int(validation.get("outside_month", 0)),
        "extraction_method": preview.get("extraction_method"),
    }


def _normal(value: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


RECEIPTS_EFFECTIVE_CTE = """WITH effective AS (
        SELECT r.receipt_id, r.duplicate_candidates_json,
        COALESCE(json_extract(a.result_json,'$.final_data.vendor'),json_extract(v.result_json,'$.final_data.vendor'),json_extract(r.extraction_json,'$.vendor')) vendor,
        COALESCE(json_extract(a.result_json,'$.final_data.legal_entity'),json_extract(v.result_json,'$.final_data.legal_entity'),json_extract(r.extraction_json,'$.legal_entity')) legal_entity,
        COALESCE(json_extract(a.result_json,'$.final_data.date'),json_extract(v.result_json,'$.final_data.date'),json_extract(r.extraction_json,'$.date')) receipt_date,
        COALESCE(json_extract(a.result_json,'$.final_data.currency'),json_extract(v.result_json,'$.final_data.currency'),json_extract(r.extraction_json,'$.currency')) currency,
        COALESCE(json_extract(a.result_json,'$.final_data.total_amount'),json_extract(v.result_json,'$.final_data.total_amount'),json_extract(r.extraction_json,'$.total_amount')) amount,
        COALESCE(json_extract(a.result_json,'$.category'),json_extract(v.result_json,'$.category'),json_extract(c.result_json,'$.category'),'Uncategorized') category,
        COALESCE(json_extract(v.result_json,'$.decision'),c.decision,r.processing_status) state
        FROM receipts r LEFT JOIN classifications c USING(receipt_id)
        LEFT JOIN receipt_reviews v USING(receipt_id)
        LEFT JOIN receipt_amendments a ON a.receipt_id=r.receipt_id AND a.version=(SELECT max(a2.version) FROM receipt_amendments a2 WHERE a2.receipt_id=r.receipt_id)
        WHERE r.lifecycle_state='ACTIVE')"""


def _receipt_rows(db, month: str, currency: str) -> list[dict]:
    rows = db.execute(
        RECEIPTS_EFFECTIVE_CTE + """
        SELECT * FROM effective WHERE state IN ('AUTO_FILED','APPROVED') AND currency=?
        AND substr(receipt_date,1,7)=? AND amount IS NOT NULL ORDER BY receipt_date, receipt_id""",
        (currency, month),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["amount_cents"] = int(
            (Decimal(str(item.pop("amount"))) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        item["vendor"] = item["vendor"] or item["legal_entity"] or "Vendor unavailable"
        item["duplicate_receipt"] = bool(json.loads(item.pop("duplicate_candidates_json") or "[]"))
        result.append(item)
    return result


def _adjacent_months(month: str) -> tuple[str | None, str | None]:
    year, number = map(int, month.split("-"))
    if year < 1 or year > 9999:
        raise StatementInvalid("Statement year must be between 0001 and 9999")
    previous = None if (year, number) == (1, 1) else (date(year - 1, 12, 1) if number == 1 else date(year, number - 1, 1))
    following = None if (year, number) == (9999, 12) else (date(year + 1, 1, 1) if number == 12 else date(year, number + 1, 1))
    return (previous.strftime("%Y-%m") if previous else None,
            following.strftime("%Y-%m") if following else None)


def _nearby_candidate(posted: str, description: str, cents: int,
                      nearby: list[dict], *, receipt_side: bool) -> dict | None:
    matches = []
    for item in nearby:
        if item["amount_cents"] != cents:
            continue
        receipt_date = posted if receipt_side else item["receipt_date"]
        bank_date = item["posted_date"] if receipt_side else posted
        if abs((date.fromisoformat(receipt_date) - date.fromisoformat(bank_date)).days) > 7:
            continue
        vendor = set(_normal(description if receipt_side else item["vendor"]).split())
        bank_text = set(_normal(item["description"] if receipt_side else description).split())
        if vendor and vendor & bank_text:
            matches.append(item)
    # Suggestions are read-only, and ambiguity must remain visible for human review.
    return matches[0] if len(matches) == 1 else None


def monthly_reconciliation(store, month: str, currency: str) -> dict:
    with store.connect() as db:
        db.execute("BEGIN")
        statements = [dict(row) for row in db.execute(
            "SELECT statement_id,account_label,original_filename,uploaded_at,row_count,skipped_rows,"
            "source_media_type,extraction_method,metadata_json,validation_json,imported_by "
            "FROM bank_statements WHERE statement_month=? AND currency=? ORDER BY uploaded_at",
            (month, currency),
        )]
        removed_statements = [
            row for row in statements if json.loads(row["metadata_json"]).get("removed", False)
        ]
        statements = [
            row for row in statements if not json.loads(row["metadata_json"]).get("removed", False)
        ]
        txs = [dict(row) for row in db.execute(
            "SELECT t.* FROM bank_transactions t JOIN bank_statements s USING(statement_id) "
            "WHERE s.statement_month=? AND s.currency=? "
            "AND COALESCE(json_extract(s.metadata_json,'$.removed'),0)=0 ORDER BY posted_date,source_row",
            (month, currency),
        )]
        receipts = _receipt_rows(db, month, currency)
        receipt_ids = {receipt["receipt_id"] for receipt in receipts}
        payment_events: dict[str, list[dict]] = {receipt_id: [] for receipt_id in receipt_ids}
        if receipt_ids:
            placeholders = ",".join("?" for _ in receipt_ids)
            for event in db.execute(
                f"SELECT receipt_id,result_json FROM receipt_payment_events WHERE receipt_id IN ({placeholders}) "
                "ORDER BY receipt_id,version DESC", tuple(receipt_ids),
            ):
                payment_events[event["receipt_id"]].append(json.loads(event["result_json"]))
        nearby_months = _adjacent_months(month)
        nearby_receipts = [receipt for near in nearby_months if near is not None
                           for receipt in _receipt_rows(db, near, currency)]
        nearby_transactions = [dict(row) for row in db.execute(
            "SELECT t.*,s.statement_month FROM bank_transactions t JOIN bank_statements s USING(statement_id) "
            "WHERE s.statement_month IN (?,?) AND s.currency=? "
            "AND COALESCE(json_extract(s.metadata_json,'$.removed'),0)=0",
            (*nearby_months, currency),
        )]

    payment_states = {
        receipt_id: events[0] for receipt_id, events in payment_events.items() if events
    }

    duplicate_keys: dict[tuple, int] = {}
    for tx in txs:
        key = (tx["posted_date"], tx["amount_cents"], _normal(tx["description"]))
        duplicate_keys[key] = duplicate_keys.get(key, 0) + 1

    unused = set(range(len(receipts)))
    matched_receipts: dict[str, str] = {}
    transaction_rows = []
    for tx in txs:
        tx_date = date.fromisoformat(tx["posted_date"])
        key = (tx["posted_date"], tx["amount_cents"], _normal(tx["description"]))
        candidates = []
        # Identical debit rows are ambiguous evidence; do not mark a receipt
        # matched to an arbitrary member of that duplicate group.
        for index in (unused if duplicate_keys[key] == 1 else ()):
            receipt = receipts[index]
            if receipt["amount_cents"] != tx["amount_cents"]:
                continue
            days = abs((tx_date - date.fromisoformat(receipt["receipt_date"])).days)
            if days > 7:
                continue
            vendor = set(_normal(receipt["vendor"]).split())
            description = set(_normal(tx["description"]).split())
            overlap = len(vendor & description) / max(1, len(vendor))
            score = 0.65 + max(0, 0.2 - days * 0.025) + min(0.15, overlap * 0.15)
            candidates.append((score, days, index))
        candidates.sort(reverse=True)
        matched = None
        if candidates and candidates[0][0] >= 0.75:
            top = candidates[0]
            if len(candidates) == 1 or top[0] - candidates[1][0] >= 0.05:
                matched = receipts[top[2]]
                unused.remove(top[2])
                matched_receipts[matched["receipt_id"]] = tx["transaction_id"]
        transaction_rows.append({
            "transaction_id": tx["transaction_id"], "statement_id": tx["statement_id"],
            "posted_date": tx["posted_date"],
            "description": tx["description"], "amount_cents": tx["amount_cents"],
            "reference": tx["reference"], "receipt_id": matched["receipt_id"] if matched else None,
            "receipt_vendor": matched["vendor"] if matched else None,
            "status": "DUPLICATE_TRANSACTION" if duplicate_keys[key] > 1 else ("MATCHED" if matched else "MISSING_RECEIPT"),
            "adjacent_month_candidate": (
                {"month": candidate["receipt_date"][:7], "receipt_id": candidate["receipt_id"]}
                if not matched and (candidate := _nearby_candidate(
                    tx["posted_date"], tx["description"], tx["amount_cents"],
                    nearby_receipts, receipt_side=False)) else None
            ),
        })

    receipt_rows = []
    for receipt in receipts:
        event = payment_states.get(receipt["receipt_id"])
        if receipt["receipt_id"] in matched_receipts:
            status = "PAID"
        elif event and event["state"] in {"TRADE_PAYABLE", "PAYMENT_ISSUE"}:
            status = event["state"]
        else:
            status = "NO_BANK_MATCH"
        receipt_rows.append({
            "receipt_id": receipt["receipt_id"], "receipt_date": receipt["receipt_date"],
            "vendor": receipt["vendor"], "category": receipt["category"],
            "amount_cents": receipt["amount_cents"], "status": status,
            "transaction_id": matched_receipts.get(receipt["receipt_id"]),
            "duplicate_receipt": receipt["duplicate_receipt"], "payment_event": event,
            "payment_events": payment_events[receipt["receipt_id"]],
            "adjacent_month_candidate": (
                {"month": candidate["statement_month"], "statement_id": candidate["statement_id"]}
                if receipt["receipt_id"] not in matched_receipts and (candidate := _nearby_candidate(
                    receipt["receipt_date"], receipt["vendor"], receipt["amount_cents"],
                    nearby_transactions, receipt_side=True)) else None
            ),
        })

    def totals_by(key: str) -> list[dict]:
        grouped: dict[str, int] = {}
        for item in receipt_rows:
            grouped[item[key]] = grouped.get(item[key], 0) + item["amount_cents"]
        return [{key: name, "total_cents": cents} for name, cents in
                sorted(grouped.items(), key=lambda pair: (-pair[1], pair[0]))]

    categories = totals_by("category")
    vendors = totals_by("vendor")
    receipt_total = sum(item["amount_cents"] for item in receipt_rows)
    bank_total = sum(item["amount_cents"] for item in transaction_rows)
    matched_total = sum(item["amount_cents"] for item in receipt_rows if item["status"] == "PAID")
    exception_count = (sum(item["status"] != "MATCHED" for item in transaction_rows)
                       + sum(item["status"] != "PAID" or item["duplicate_receipt"] for item in receipt_rows))
    suggestions = []
    if categories:
        share = round(categories[0]["total_cents"] / max(1, receipt_total) * 100)
        suggestions.append({"title": f"Review {categories[0]['category']}",
                            "detail": f"It is the largest category at {share}% of accepted receipt spend. Compare recurring charges and request fresh quotes before renewal."})
    if vendors:
        share = round(vendors[0]["total_cents"] / max(1, receipt_total) * 100)
        suggestions.append({"title": f"Check concentration with {vendors[0]['vendor']}",
                            "detail": f"This vendor represents {share}% of accepted receipt spend. Review contract terms, usage, and at least one comparable quote."})
    if exception_count:
        suggestions.append({"title": "Resolve evidence gaps first",
                            "detail": f"There are {exception_count} reconciliation exceptions. Clear duplicates and missing evidence before relying on savings estimates."})
    return {
        "month": month, "currency": currency, "statements": statements,
        "removed_statements": removed_statements,
        "transactions": transaction_rows, "receipts": receipt_rows,
        "totals": {"bank_debits_cents": bank_total, "receipt_spend_cents": receipt_total,
                   "matched_cents": matched_total, "difference_cents": bank_total - receipt_total,
                   "exception_count": exception_count},
        "categories": categories, "vendors": vendors, "suggestions": suggestions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _period_fingerprint(store, data: dict) -> str:
    ids = [receipt["receipt_id"] for receipt in data["receipts"]]
    with store.connect() as db:
        revisions = [tuple(row) for row in db.execute(
            "SELECT receipt_id,updated_at FROM receipts WHERE receipt_id IN ("
            + ",".join("?" for _ in ids) + ") ORDER BY receipt_id", ids,
        )] if ids else []
    payload = {
        "statements": data["statements"], "removed_statements": data["removed_statements"],
        "transactions": data["transactions"], "receipts": data["receipts"],
        "revisions": revisions,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def period_review(store, data: dict) -> dict:
    fingerprint = _period_fingerprint(store, data)
    with store.connect() as db:
        latest = db.execute(
            "SELECT actor,note,reviewed_at,fingerprint FROM monthly_close_reviews "
            "WHERE month=? AND currency=? ORDER BY id DESC LIMIT 1",
            (data["month"], data["currency"]),
        ).fetchone()
    return {
        "fingerprint": fingerprint,
        "status": "not_reviewed" if latest is None else
                  ("reviewed" if hmac.compare_digest(fingerprint, latest["fingerprint"]) else "outdated"),
        "actor": latest["actor"] if latest else None,
        "note": latest["note"] if latest else None,
        "reviewed_at": latest["reviewed_at"] if latest else None,
    }


def reconciliation_detail(store, month: str, currency: str) -> dict:
    data = monthly_reconciliation(store, month, currency)
    data["review"] = period_review(store, data)
    return data


def record_month_review(store, body: MonthReviewRequest) -> dict:
    # Serialize with imports and edits so a stale screen cannot certify a changed month.
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        data = monthly_reconciliation(store, body.month, body.currency)
        if not data["statements"]:
            raise StatementInvalid("Import a statement before recording a monthly review")
        fingerprint = _period_fingerprint(store, data)
        if not hmac.compare_digest(fingerprint, body.fingerprint):
            raise StatementInvalid("This month changed while you were reviewing it. Refresh and check it again.")
        reviewed_at = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO monthly_close_reviews (month,currency,actor,note,reviewed_at,fingerprint) "
                   "VALUES (?,?,?,?,?,?)", (body.month, body.currency, body.actor,
                                            body.note, reviewed_at, fingerprint))
    return {"month": body.month, "currency": body.currency, "actor": body.actor,
            "note": body.note, "reviewed_at": reviewed_at, "status": "reviewed"}


def list_periods(store) -> list[dict]:
    with store.connect() as db:
        statements = [dict(row) for row in db.execute(
            "SELECT statement_month AS month,currency,"
            "sum(CASE WHEN COALESCE(json_extract(metadata_json,'$.removed'),0)=0 THEN 1 ELSE 0 END) AS statement_count,"
            "sum(CASE WHEN COALESCE(json_extract(metadata_json,'$.removed'),0)=0 THEN row_count ELSE 0 END) AS transaction_count "
            "FROM bank_statements GROUP BY statement_month,currency ORDER BY statement_month DESC,currency"
        )]
        receipt_periods = [dict(row) for row in db.execute(
            RECEIPTS_EFFECTIVE_CTE + " SELECT substr(receipt_date,1,7) AS month,currency,"
            "count(*) AS receipt_count FROM effective WHERE state IN ('AUTO_FILED','APPROVED') "
            "AND receipt_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-*' "
            "AND amount IS NOT NULL AND currency IS NOT NULL GROUP BY month,currency"
        )]
    periods = {(row["month"], row["currency"]): row for row in statements}
    for row in receipt_periods:
        key = (row["month"], row["currency"])
        periods.setdefault(key, {"month": row["month"], "currency": row["currency"],
                                 "statement_count": 0, "transaction_count": 0})
    result = []
    for month, currency in sorted(periods, reverse=True):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) or not re.fullmatch(r"[A-Z]{3}", currency):
            continue
        data = monthly_reconciliation(store, month, currency)
        item = {**periods[(month, currency)], "receipt_count": len(data["receipts"]),
                "exception_count": data["totals"]["exception_count"],
                "bank_missing_count": sum(tx["status"] == "MISSING_RECEIPT" for tx in data["transactions"]),
                "receipt_unmatched_count": sum(r["status"] != "PAID" for r in data["receipts"]),
                "duplicate_count": sum(tx["status"] == "DUPLICATE_TRANSACTION" for tx in data["transactions"])
                                   + sum(r["duplicate_receipt"] for r in data["receipts"]),
                "review": period_review(store, data)}
        result.append(item)
    return result


def statement_source(store, statement_id: str) -> tuple[str, str, bytes]:
    with store.connect() as db:
        row = db.execute(
            "SELECT original_filename,source_media_type,source_csv FROM bank_statements WHERE statement_id=?",
            (statement_id,),
        ).fetchone()
    if not row:
        raise StatementInvalid("Bank statement was not found")
    return row[0], row[1], bytes(row[2])


def update_payment_state(store, receipt_id: str, body: PaymentUpdate) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT r.lifecycle_state,COALESCE(json_extract(v.result_json,'$.decision'),c.decision,r.processing_status) "
            "FROM receipts r LEFT JOIN classifications c USING(receipt_id) "
            "LEFT JOIN receipt_reviews v USING(receipt_id) WHERE r.receipt_id=?",
            (receipt_id,),
        ).fetchone()
        if not row:
            raise StatementInvalid("Receipt was not found")
        if row[0] != "ACTIVE":
            raise StatementInvalid("Only active receipts can receive a payment status")
        if row[1] not in {"AUTO_FILED", "APPROVED"}:
            raise StatementInvalid("Only approved or auto-filed receipts can receive a payment status")
        latest = db.execute("SELECT version,result_json FROM receipt_payment_events "
                            "WHERE receipt_id=? ORDER BY version DESC LIMIT 1", (receipt_id,)).fetchone()
        current_version = latest["version"] if latest else 0
        if body.expected_version is not None and body.expected_version != current_version:
            raise StatementInvalid("Payment status changed. Refresh the receipt and review the latest event.")
        previous = json.loads(latest["result_json"]) if latest else None
        version = current_version + 1
        event = {"state": body.state, "actor": body.actor.strip(), "note": body.note.strip(),
                 "occurred_at": timestamp, "version": version,
                 "previous_state": previous["state"] if previous and previous["state"] != "CLEAR" else "NO_BANK_MATCH",
                 "previous_invoice_due_date": previous.get("invoice_due_date") if previous else None,
                 "previous_planned_payment_date": previous.get("planned_payment_date") if previous else None,
                 "invoice_due_date": body.invoice_due_date.isoformat() if body.invoice_due_date else None,
                 "planned_payment_date": body.planned_payment_date.isoformat() if body.planned_payment_date else None}
        db.execute("INSERT INTO receipt_payment_events VALUES (?,?,?)",
                   (receipt_id, version, json.dumps(event, allow_nan=False)))
    return event


def build_monthly_export(store, month: str, currency: str) -> bytes:
    import xlsxwriter

    data = reconciliation_detail(store, month, currency)
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(
        output,
        {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False},
    )
    title = workbook.add_format({"bold": True, "font_size": 16, "font_color": "#17324D"})
    subtitle = workbook.add_format({"font_size": 9, "font_color": "#64748B", "italic": True})
    section = workbook.add_format({"bold": True, "font_color": "#17324D", "bottom": 2, "bottom_color": "#B8CBD8"})
    label = workbook.add_format({"bold": True, "font_color": "#526577", "font_size": 9})
    money = workbook.add_format({"num_format": f'"{currency}" #,##0.00;[Red]("{currency}" #,##0.00);-'})
    percent = workbook.add_format({"num_format": "0.0%"})
    kpi = workbook.add_format({"bold": True, "font_size": 14, "font_color": "#17324D", "bg_color": "#EDF5F7", "border": 1, "border_color": "#D5E3E8", "num_format": f'"{currency}" #,##0.00;[Red]("{currency}" #,##0.00);-'})
    kpi_count = workbook.add_format({"bold": True, "font_size": 14, "font_color": "#9A3412", "bg_color": "#FFF4E5", "border": 1, "border_color": "#FED7AA", "num_format": "#,##0"})
    total_label = workbook.add_format({"bold": True, "top": 1, "top_color": "#94A3B8"})
    total_money = workbook.add_format({"bold": True, "top": 1, "top_color": "#94A3B8", "num_format": f'"{currency}" #,##0.00;[Red]("{currency}" #,##0.00);-'})
    issue = workbook.add_format({"bg_color": "#FDECEC", "font_color": "#9F1239"})
    suggestion = workbook.add_format({"bg_color": "#EFF6FF", "font_color": "#1E40AF"})

    def add_table(sheet, name: str, start_row: int, headers: list[str], rows: list[list[object]],
                  style: str = "Table Style Medium 2") -> None:
        if rows:
            sheet.add_table(start_row, 0, start_row + len(rows), len(headers) - 1, {
                "name": name, "style": style,
                "columns": [{"header": value} for value in headers], "data": rows,
            })
        else:
            empty_header = workbook.add_format({"bold": True, "bg_color": "#245C65", "font_color": "#FFFFFF"})
            sheet.write_row(start_row, 0, headers, empty_header)
            sheet.autofilter(start_row, 0, start_row, len(headers) - 1)
            sheet.write(start_row + 1, 0, "No records for this period.", subtitle)

    summary = workbook.add_worksheet("Summary")
    summary.hide_gridlines(2)
    summary.set_landscape(); summary.fit_to_pages(1, 1); summary.set_margins(0.35, 0.35, 0.5, 0.5)
    summary.set_tab_color("#17324D")
    summary.set_column("A:A", 40); summary.set_column("B:E", 18); summary.set_column("F:F", 3); summary.set_column("G:L", 17)
    summary.write("A2", "Monthly close", title)
    summary.write("A3", f"{month} · {currency} · generated {data['generated_at'][:16].replace('T', ' ')} UTC · debit-only source", subtitle)
    kpis = [
        ("Bank debits", data["totals"]["bank_debits_cents"] / 100, kpi),
        ("Accepted receipts", data["totals"]["receipt_spend_cents"] / 100, kpi),
        ("Suggested matches", data["totals"]["matched_cents"] / 100, kpi),
        ("Exceptions", data["totals"]["exception_count"], kpi_count),
    ]
    for index, (name, value, value_format) in enumerate(kpis):
        column = index + 1
        summary.write(5, column, name, label)
        summary.write_number(6, column, value, value_format)

    summary.write("A10", "Evidence comparison", section)
    receipt_spend_cents = data["totals"]["receipt_spend_cents"]
    summary_rows = [
        ["Bank debits", data["totals"]["bank_debits_cents"] / 100],
        ["Accepted receipt spend", data["totals"]["receipt_spend_cents"] / 100],
        ["Suggested matched receipt spend", data["totals"]["matched_cents"] / 100],
        ["Bank debits minus accepted receipts", data["totals"]["difference_cents"] / 100],
    ]
    add_table(summary, "MonthlyReconciliationTotals", 10, ["Measure", "Amount"], summary_rows)
    summary.set_column("B:B", 18, money)
    summary.write(16, 0, "Suggested match coverage", label)
    if receipt_spend_cents:
        summary.write_number(16, 1, data["totals"]["matched_cents"] / receipt_spend_cents, percent)
    else:
        summary.write(16, 1, "N/A — no accepted spend", subtitle)
    summary.merge_range("A19:E19", "Bank matches are suggestions, not proof of payment. Compare retained statements with receipts before confirming a month.", subtitle)

    review = data["review"]
    summary.write("G10", "Monthly review", section)
    summary.write("G11", "Status", label)
    summary.write("H11", review["status"].replace("_", " ").title())
    summary.write("G12", "Reviewed by", label)
    summary.write("H12", review["actor"] or "Not reviewed")
    summary.write("G13", "Reviewed at", label)
    summary.write("H13", review["reviewed_at"] or "—")
    if review["note"]:
        summary.write("G14", "Review note", label)
        summary.merge_range("H14:L16", review["note"], workbook.add_format({"text_wrap": True, "valign": "top"}))

    category_start = 19
    summary.write(category_start, 0, "Spend by category", section)
    category_rows = [[item["category"], item["total_cents"] / 100,
                      item["total_cents"] / max(1, data["totals"]["receipt_spend_cents"])]
                     for item in data["categories"]]
    if category_rows:
        summary.add_table(category_start + 1, 0, category_start + 1 + len(category_rows), 2, {
            "name": "MonthlyCategorySpend", "style": "Table Style Medium 2",
            "columns": [{"header": "Category"}, {"header": "Amount"}, {"header": "Share"}],
            "data": category_rows,
        })
        summary.set_column("B:B", 18, money); summary.set_column("C:C", 22, percent)

    vendor_start = category_start + max(6, len(category_rows) + 4)
    summary.write(vendor_start, 0, "Spend by company", section)
    vendor_rows = [[item["vendor"], item["total_cents"] / 100,
                    item["total_cents"] / max(1, data["totals"]["receipt_spend_cents"])]
                   for item in data["vendors"]]
    if vendor_rows:
        summary.add_table(vendor_start + 1, 0, vendor_start + 1 + len(vendor_rows), 2, {
            "name": "MonthlyVendorSpend", "style": "Table Style Medium 4",
            "columns": [{"header": "Company"}, {"header": "Amount"}, {"header": "Share"}],
            "data": vendor_rows,
        })
        summary.set_column("B:B", 18, money); summary.set_column("C:C", 22, percent)
    summary.freeze_panes(9, 0)

    tx_sheet = workbook.add_worksheet("Bank transactions")
    tx_sheet.hide_gridlines(2); tx_sheet.set_tab_color("#2A6F75")
    tx_sheet.set_landscape(); tx_sheet.fit_to_pages(2, 0); tx_sheet.set_margins(0.35, 0.35, 0.5, 0.5)
    tx_sheet.write("A2", "Imported bank debits", title)
    tx_sheet.write("A3", f"{month} · {currency}. Credits are excluded; matches are suggestions pending evidence review.", subtitle)
    source_names = {item["statement_id"]: item["original_filename"] for item in data["statements"]}
    tx_headers = ["Date", "Description", "Debit", "Reference", "Status", "Suggested receipt ID",
                  "Suggested vendor", "Statement filename", "Statement ID", "Adjacent-month receipt"]
    tx_rows = [[item["posted_date"], item["description"], item["amount_cents"] / 100,
                item["reference"], item["status"], item["receipt_id"], item["receipt_vendor"],
                source_names.get(item["statement_id"]), item["statement_id"],
                ((item["adjacent_month_candidate"]["month"] + " · " + item["adjacent_month_candidate"]["receipt_id"])
                 if item["adjacent_month_candidate"] else None)]
               for item in data["transactions"]]
    add_table(tx_sheet, "MonthlyBankTransactions", 4, tx_headers, tx_rows)
    tx_sheet.set_column("A:A", 13); tx_sheet.set_column("B:B", 42); tx_sheet.set_column("C:C", 18, money); tx_sheet.set_column("D:F", 22)
    tx_sheet.set_column("G:H", 26); tx_sheet.set_column("I:J", 42)
    tx_sheet.freeze_panes(5, 0)
    tx_sheet.repeat_rows(4)
    if tx_rows:
        tx_sheet.conditional_format(5, 4, 4 + len(tx_rows), 4, {"type": "text", "criteria": "containing", "value": "MATCHED", "format": suggestion})
        for value in ("MISSING", "DUPLICATE"):
            tx_sheet.conditional_format(5, 4, 4 + len(tx_rows), 4, {"type": "text", "criteria": "containing", "value": value, "format": issue})
        total_row = 6 + len(tx_rows)
        tx_sheet.write(total_row, 1, "Total bank debits", total_label)
        tx_sheet.write_number(total_row, 2, data["totals"]["bank_debits_cents"] / 100, total_money)

    receipt_sheet = workbook.add_worksheet("Receipts")
    receipt_sheet.hide_gridlines(2); receipt_sheet.set_tab_color("#2A6F75")
    receipt_sheet.set_landscape(); receipt_sheet.fit_to_pages(2, 0); receipt_sheet.set_margins(0.35, 0.35, 0.5, 0.5)
    receipt_sheet.write("A2", "Accepted receipts", title)
    receipt_sheet.write("A3", f"Receipts dated in {month}. PAID is a suggested bank match; payable/issue statuses are recorded by a person.", subtitle)
    receipt_headers = ["Date", "Vendor", "Category", "Amount", "Reconciliation status", "Duplicate flag",
                       "Receipt ID", "Suggested debit ID", "Invoice due", "Planned payment"]
    receipt_rows = [[item["receipt_date"], item["vendor"], item["category"], item["amount_cents"] / 100,
                     "SUGGESTED_BANK_MATCH" if item["status"] == "PAID" else item["status"],
                     "Yes" if item["duplicate_receipt"] else "No", item["receipt_id"], item["transaction_id"],
                     (item["payment_event"] or {}).get("invoice_due_date"),
                     (item["payment_event"] or {}).get("planned_payment_date")]
                    for item in data["receipts"]]
    add_table(receipt_sheet, "MonthlyAcceptedReceipts", 4, receipt_headers, receipt_rows)
    receipt_sheet.set_column("A:A", 13); receipt_sheet.set_column("B:C", 30); receipt_sheet.set_column("D:D", 18, money); receipt_sheet.set_column("E:G", 20)
    receipt_sheet.set_column("H:H", 38); receipt_sheet.set_column("I:J", 18)
    receipt_sheet.freeze_panes(5, 0)
    receipt_sheet.repeat_rows(4)
    if receipt_rows:
        receipt_sheet.conditional_format(5, 4, 4 + len(receipt_rows), 4, {"type": "text", "criteria": "containing", "value": "SUGGESTED_BANK_MATCH", "format": suggestion})
        for value in ("NO_BANK_MATCH", "PAYMENT_ISSUE", "TRADE_PAYABLE"):
            receipt_sheet.conditional_format(5, 4, 4 + len(receipt_rows), 4, {"type": "text", "criteria": "containing", "value": value, "format": issue})
        receipt_sheet.conditional_format(5, 5, 4 + len(receipt_rows), 5, {"type": "text", "criteria": "containing", "value": "Yes", "format": issue})
        total_row = 6 + len(receipt_rows)
        receipt_sheet.write(total_row, 2, "Total accepted receipts", total_label)
        receipt_sheet.write_number(total_row, 3, data["totals"]["receipt_spend_cents"] / 100, total_money)

    source_sheet = workbook.add_worksheet("Statement sources")
    source_sheet.hide_gridlines(2); source_sheet.set_tab_color("#7BA7AE")
    source_sheet.set_landscape(); source_sheet.fit_to_pages(1, 0); source_sheet.set_margins(0.35, 0.35, 0.5, 0.5)
    source_sheet.write("A2", "Retained statement sources", title)
    source_sheet.write("A3", "Original files remain available in Ledgerly for evidence review.", subtitle)
    source_headers = ["Statement ID", "Account", "Filename", "Imported by", "Uploaded at", "Debit rows", "Skipped rows", "Media type", "Extraction"]
    source_rows = [[item["statement_id"], item["account_label"], item["original_filename"], item.get("imported_by"), item["uploaded_at"],
                    item["row_count"], item["skipped_rows"], item.get("source_media_type"), item.get("extraction_method")]
                   for item in data["statements"]]
    add_table(source_sheet, "MonthlyStatementSources", 4, source_headers, source_rows, "Table Style Medium 4")
    source_sheet.set_column("A:A", 38); source_sheet.set_column("B:D", 25); source_sheet.set_column("E:E", 24); source_sheet.set_column("F:I", 16)
    source_sheet.freeze_panes(5, 0)
    source_sheet.repeat_rows(4)

    payment_sheet = workbook.add_worksheet("Payment audit")
    payment_sheet.hide_gridlines(2); payment_sheet.set_tab_color("#7BA7AE")
    payment_sheet.set_landscape(); payment_sheet.fit_to_pages(2, 0)
    payment_sheet.set_margins(0.35, 0.35, 0.5, 0.5)
    payment_sheet.write("A2", "Payment status history", title)
    payment_sheet.write("A3", "Human-entered status events only. A suggested bank match is not a recorded payment decision.", subtitle)
    payment_headers = ["Receipt ID", "Version", "Recorded at (UTC)", "State", "Previous state",
                       "Actor", "Reason", "Invoice due", "Planned payment"]
    payment_rows = [[receipt["receipt_id"], event["version"], event["occurred_at"],
                     event["state"], event.get("previous_state"), event["actor"], event["note"],
                     event.get("invoice_due_date"), event.get("planned_payment_date")]
                    for receipt in data["receipts"] for event in reversed(receipt["payment_events"])]
    add_table(payment_sheet, "MonthlyPaymentAudit", 4, payment_headers, payment_rows, "Table Style Medium 4")
    payment_sheet.set_column("A:A", 38); payment_sheet.set_column("B:B", 10)
    payment_sheet.set_column("C:C", 26); payment_sheet.set_column("D:F", 21)
    payment_sheet.set_column("G:G", 44); payment_sheet.set_column("H:I", 18)
    payment_sheet.freeze_panes(5, 0)
    payment_sheet.repeat_rows(4)

    workbook.set_properties({"title": f"Ledgerly reconciliation {month}", "author": "Ledgerly"})
    workbook.close()
    return output.getvalue()
