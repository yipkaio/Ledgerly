"""Append-only corrections for accepted receipts."""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.classification import ExpenseCategory
from app.extraction import GatewayReceiptExtractor, ReceiptExtraction
from app.review import (
    ReviewConflict,
    ReviewInvalid,
    ReviewNotFound,
    SUPPORTED_REVIEW_CURRENCIES,
    reject_placeholder,
)


class AmendmentRequest(BaseModel):
    """A complete replacement view; source evidence remains immutable."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID = Field(
        description="New UUID for this amendment; reuse only for an identical retry."
    )
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    reviewer: Annotated[str, Field(min_length=1, max_length=100)]
    reason: Annotated[str, Field(min_length=10, max_length=2000)]
    evidence_confirmed: Literal[True]
    final_data: ReceiptExtraction
    category: ExpenseCategory
    override_reason: Annotated[str | None, Field(min_length=10, max_length=2000)] = None

    @field_validator("evidence_confirmed", mode="before")
    @classmethod
    def require_boolean_true(cls, value):
        if value is not True:
            raise ValueError("evidence_confirmed must be the JSON boolean true")
        return value

    @field_validator("reviewer", "reason", "override_reason")
    @classmethod
    def reject_example_text(cls, value):
        reject_placeholder(value)
        return value

    @model_validator(mode="after")
    def validate_final_data(self):
        reject_placeholder(self.final_data.model_dump(mode="json"))
        required = (
            self.final_data.vendor,
            self.final_data.date,
            self.final_data.currency,
            self.final_data.total_amount,
        )
        if any(value is None for value in required):
            raise ValueError(
                "Amendment requires vendor, date, currency and total_amount"
            )
        if self.final_data.currency not in SUPPORTED_REVIEW_CURRENCIES:
            raise ValueError(
                "Unsupported review currency. Supported: "
                + ", ".join(sorted(SUPPORTED_REVIEW_CURRENCIES))
            )
        return self


AMENDMENT_SCHEMA = (
    "CREATE TABLE receipt_amendments (receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id), "
    "version INTEGER NOT NULL CHECK(version>0), request_id TEXT NOT NULL UNIQUE, "
    "request_json TEXT NOT NULL, result_json TEXT NOT NULL, "
    "PRIMARY KEY(receipt_id, version))",
    "CREATE TABLE amendment_audit (receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id), "
    "version INTEGER NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY(receipt_id, version))",
    "CREATE TRIGGER receipt_amendments_no_update BEFORE UPDATE ON receipt_amendments "
    "BEGIN SELECT RAISE(ABORT, 'Immutable amendment'); END",
    "CREATE TRIGGER receipt_amendments_no_delete BEFORE DELETE ON receipt_amendments "
    "BEGIN SELECT RAISE(ABORT, 'Immutable amendment'); END",
    "CREATE TRIGGER amendment_audit_no_update BEFORE UPDATE ON amendment_audit "
    "BEGIN SELECT RAISE(ABORT, 'Immutable audit'); END",
    "CREATE TRIGGER amendment_audit_no_delete BEFORE DELETE ON amendment_audit "
    "BEGIN SELECT RAISE(ABORT, 'Immutable audit'); END",
)


def _original_data(db, row) -> dict:
    data = json.loads(row["extraction_json"])
    data["line_items"] = [
        json.loads(item[0])
        for item in db.execute(
            "SELECT item_json FROM line_items WHERE receipt_id=? ORDER BY position",
            (row["receipt_id"],),
        )
    ]
    return data


def _effective_before(db, row) -> tuple[dict, str, str, int]:
    latest = db.execute(
        "SELECT result_json, version FROM receipt_amendments WHERE receipt_id=? "
        "ORDER BY version DESC LIMIT 1",
        (row["receipt_id"],),
    ).fetchone()
    review = db.execute(
        "SELECT result_json FROM receipt_reviews WHERE receipt_id=?",
        (row["receipt_id"],),
    ).fetchone()
    classification = json.loads(
        db.execute(
            "SELECT result_json FROM classifications WHERE receipt_id=?",
            (row["receipt_id"],),
        ).fetchone()[0]
    )
    if latest:
        result = json.loads(latest[0])
        return result["final_data"], result["category"], "AMENDED", latest[1]
    if review:
        result = json.loads(review[0])
        if result["decision"] != "APPROVED":
            raise ReviewConflict("Rejected receipts cannot be amended")
        return result["final_data"], result["category"], "APPROVED", 1
    if row["processing_status"] != "COMPLETED":
        raise ReviewConflict("Only auto-filed or approved receipts can be amended")
    return _original_data(db, row), classification["category"], "AUTO_FILED", 0


def submit_amendment(store, receipt_id: str, request: AmendmentRequest) -> dict:
    from app.database import now

    request_json = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, allow_nan=False
    )
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT receipt_id, request_json, result_json FROM receipt_amendments "
            "WHERE request_id=?",
            (str(request.request_id),),
        ).fetchone()
        if prior:
            if prior["receipt_id"] == receipt_id and prior["request_json"] == request_json:
                return json.loads(prior["result_json"])
            raise ReviewConflict("Request ID was already used with different content")
        row = db.execute(
            "SELECT * FROM receipts WHERE receipt_id=?", (receipt_id,)
        ).fetchone()
        if row is None:
            raise ReviewNotFound("Receipt not found")
        before_data, before_category, before_state, current_version = _effective_before(
            db, row
        )
        if request.expected_version != current_version:
            raise ReviewConflict("Receipt record version is stale")

        clean = request.final_data.model_copy(
            update={"needs_review": False, "review_reasons": []}
        )
        checked = GatewayReceiptExtractor._apply_deterministic_checks(
            clean, repair_swaps=False
        )
        issues = checked.review_reasons
        if issues and not request.override_reason:
            raise ReviewInvalid(
                "Unresolved validation issues require override_reason: "
                + "; ".join(issues)
            )
        version = current_version + 1
        result = {
            "receipt_id": receipt_id,
            "record_version": version,
            "request_id": str(request.request_id),
            "event_type": "AMENDMENT",
            "reviewer": request.reviewer,
            "identity_source": "self_reported",
            "amended_at": now(),
            "reason": request.reason,
            "evidence_confirmed": True,
            "final_data": checked.model_dump(mode="json"),
            "category": request.category.value,
            "validation_issues": issues,
            "override_reason": request.override_reason,
        }
        event = {
            **result,
            "before": {
                "record_version": current_version,
                "state": before_state,
                "final_data": before_data,
                "category": before_category,
            },
        }
        result_json = json.dumps(result, allow_nan=False)
        db.execute(
            "INSERT INTO receipt_amendments VALUES (?, ?, ?, ?, ?)",
            (receipt_id, version, str(request.request_id), request_json, result_json),
        )
        db.execute(
            "INSERT INTO amendment_audit VALUES (?, ?, ?)",
            (receipt_id, version, json.dumps(event, allow_nan=False)),
        )
        return result


def amendment_history(store, receipt_id: str) -> dict:
    with store.connect() as db:
        db.execute("BEGIN")
        if not db.execute(
            "SELECT 1 FROM receipts WHERE receipt_id=?", (receipt_id,)
        ).fetchone():
            raise ReviewNotFound("Receipt not found")
        rows = db.execute(
            "SELECT event_json FROM amendment_audit WHERE receipt_id=? ORDER BY version",
            (receipt_id,),
        ).fetchall()
    return {"items": [json.loads(row[0]) for row in rows]}

