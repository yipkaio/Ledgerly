"""Private, single-workspace human review. Original AI evidence is immutable here."""

import json
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.classification import ExpenseCategory
from app.extraction import ReceiptExtraction, GatewayReceiptExtractor

# Explicit MVP scope, not a complete currency registry. Never convert unknown codes.
SUPPORTED_REVIEW_CURRENCIES = frozenset({"SGD", "MYR", "USD", "EUR", "GBP", "AUD"})


def reject_placeholder(value):
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if (not normalized or re.fullmatch(r"(?:string)+(?:s|st|str|stri|strin)?", normalized)
                or normalized in {"placeholder", "todo", "your name", "replace me"}
                or normalized.startswith("replace_")):
            raise ValueError("Replace placeholder or blank text with verified information; use null for absent optional receipt fields")
    elif isinstance(value, dict):
        for key, item in value.items():
            if key != "review_reasons":
                reject_placeholder(item)
    elif isinstance(value, list):
        for item in value:
            reject_placeholder(item)


class ReviewConflict(ValueError):
    pass


class ReviewNotFound(ValueError):
    pass


class ReviewInvalid(ValueError):
    pass


def same_saved_request(saved: str, current: str) -> bool:
    """A missing optional draft link in pre-v5 requests still means null."""
    left, right = json.loads(saved), json.loads(current)
    for value in (left, right):
        if value.get('reprocess_request_id') is None:
            value.pop('reprocess_request_id', None)
    return left == right


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID = Field(description="Generate a new UUID for each decision. Reuse the same UUID and identical payload only for retries.")
    expected_version: Annotated[int, Field(strict=True, ge=0, description="Copy review_version from receipt detail. Only pending version 0 can be finalized.")]
    decision: Literal["APPROVED", "REJECTED"]
    reviewer: Annotated[str, Field(min_length=1, max_length=100)]
    note: Annotated[str, Field(min_length=1, max_length=2000)]
    evidence_confirmed: Literal[True] = Field(description="Set true only after checking the original receipt image. This cannot verify that you actually viewed it.")
    corrected_data: ReceiptExtraction | None = Field(default=None, description="Approval: copy the COMPLETE extracted_data from GET receipt detail, then correct verified fields. Rejection: omit.")
    category: ExpenseCategory | None = None
    reprocess_request_id: UUID | None = None
    override_reason: Annotated[str | None, Field(min_length=10, max_length=2000)] = None

    @field_validator("evidence_confirmed", mode="before")
    @classmethod
    def require_actual_confirmation(cls, value):
        if value is not True:
            raise ValueError("evidence_confirmed must be the JSON boolean true")
        return value

    @field_validator("reviewer", "note", "override_reason")
    @classmethod
    def reject_example_text(cls, value):
        reject_placeholder(value)
        return value

    @model_validator(mode="after")
    def check_decision(self):
        if self.decision == "APPROVED" and (self.corrected_data is None or self.category is None):
            raise ValueError("Approval requires complete corrected_data and category")
        if self.decision == "REJECTED" and (self.corrected_data is not None or self.category is not None or self.override_reason is not None):
            raise ValueError("Rejection accepts a note, not corrections or overrides")
        if self.corrected_data is not None:
            data = self.corrected_data
            reject_placeholder(data.model_dump(mode="json"))
            if any(value is None for value in (data.vendor, data.date, data.currency, data.total_amount)):
                raise ValueError("Approval requires vendor, date, currency and total_amount; override_reason cannot bypass these requirements")
            if data.currency not in SUPPORTED_REVIEW_CURRENCIES:
                raise ValueError("Unsupported review currency. Supported: " + ", ".join(sorted(SUPPORTED_REVIEW_CURRENCIES)))
        return self


REVIEW_SCHEMA = (
    "CREATE TABLE receipt_reviews (receipt_id TEXT PRIMARY KEY REFERENCES receipts(receipt_id), "
    "request_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL, result_json TEXT NOT NULL)",
    "CREATE TABLE review_audit (receipt_id TEXT PRIMARY KEY REFERENCES receipts(receipt_id), "
    "event_json TEXT NOT NULL)",
    "CREATE TRIGGER review_audit_no_update BEFORE UPDATE ON review_audit BEGIN SELECT RAISE(ABORT, 'Immutable audit'); END",
    "CREATE TRIGGER review_audit_no_delete BEFORE DELETE ON review_audit BEGIN SELECT RAISE(ABORT, 'Immutable audit'); END",
)


def pending_reviews(store, limit: int, offset: int) -> dict:
    with store.connect() as db:
        db.execute("BEGIN")
        source = " FROM receipts r WHERE processing_status='REVIEW_QUEUE' AND lifecycle_state='ACTIVE' AND NOT EXISTS (SELECT 1 FROM receipt_reviews v WHERE v.receipt_id=r.receipt_id)"
        total = db.execute("SELECT count(*)" + source).fetchone()[0]
        rows = db.execute("SELECT receipt_id, created_at, 0 AS review_version, "
                          "json_extract(extraction_json, '$.vendor') AS vendor, "
                          "json_extract(extraction_json, '$.total_amount') AS total_amount, "
                          "json_extract(extraction_json, '$.currency') AS currency" + source +
                          " ORDER BY created_at, receipt_id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def review_history(store, receipt_id: str) -> dict:
    with store.connect() as db:
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone():
            raise ReviewNotFound("Receipt not found")
        rows = db.execute("SELECT event_json FROM review_audit WHERE receipt_id=?", (receipt_id,)).fetchall()
    return {"items": [json.loads(row[0]) for row in rows]}


def submit_review(store, receipt_id: str, request: ReviewRequest) -> dict:
    from app.database import now

    request_json = json.dumps(request.model_dump(mode="json"), sort_keys=True, allow_nan=False)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT * FROM receipt_reviews WHERE request_id=?", (str(request.request_id),)).fetchone()
        if prior:
            if prior['receipt_id'] == receipt_id and same_saved_request(prior['request_json'], request_json):
                return json.loads(prior['result_json'])
            raise ReviewConflict("Request ID was already used with different content")
        row = db.execute("SELECT * FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
        if row is None:
            raise ReviewNotFound("Receipt not found")
        if row['lifecycle_state'] != 'ACTIVE':
            raise ReviewConflict("Deleted or voided receipts cannot be reviewed")
        if request.expected_version != 0 or db.execute("SELECT 1 FROM receipt_reviews WHERE receipt_id=?", (receipt_id,)).fetchone():
            raise ReviewConflict("Receipt review version is stale or already finalized")
        if row['processing_status'] != 'REVIEW_QUEUE':
            raise ReviewConflict("Only queued receipts can be reviewed")
        from app.reprocessing import validate_source
        validate_source(db, receipt_id, request.reprocess_request_id)
        before = json.loads(row['extraction_json']) if row['extraction_json'] else {}
        before['line_items'] = [json.loads(item[0]) for item in db.execute(
            "SELECT item_json FROM line_items WHERE receipt_id=? ORDER BY position", (receipt_id,))]
        classification_row = db.execute(
            "SELECT result_json FROM classifications WHERE receipt_id=?", (receipt_id,)).fetchone()
        original_classification = json.loads(classification_row[0]) if classification_row else None
        final_data = None
        issues = []
        if request.corrected_data is not None:
            clean = request.corrected_data.model_copy(update={"needs_review": False, "review_reasons": []})
            checked = GatewayReceiptExtractor._apply_deterministic_checks(clean, repair_swaps=False)
            issues = checked.review_reasons
            if issues and not request.override_reason:
                raise ReviewInvalid("Unresolved validation issues require override_reason: " + "; ".join(issues))
            final_data = checked.model_dump(mode="json")
        result = {
            "receipt_id": receipt_id, "review_version": 1, "request_id": str(request.request_id),
            "reprocess_request_id": str(request.reprocess_request_id) if request.reprocess_request_id else None,
            "decision": request.decision, "reviewer": request.reviewer,
            "identity_source": "self_reported", "reviewed_at": now(), "note": request.note,
            "evidence_confirmed": True, "final_data": final_data,
            "category": request.category.value if request.category else None,
            "validation_issues": issues, "override_reason": request.override_reason,
        }
        event = {**result, "before": {"extracted_data": before, "classification": original_classification}}
        db.execute("INSERT INTO receipt_reviews VALUES (?, ?, ?, ?)",
                   (receipt_id, str(request.request_id), request_json, json.dumps(result, allow_nan=False)))
        db.execute("INSERT INTO review_audit VALUES (?, ?)", (receipt_id, json.dumps(event, allow_nan=False)))
        return result
