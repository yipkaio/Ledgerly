"""Bounded XLSX exports built from one immutable SQLite read snapshot."""

from __future__ import annotations

from io import BytesIO
import json
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
import xlsxwriter

from app.history import HISTORY_CTE, HistoryFilters, filter_clause


SELECTED_EXPORT_LIMIT = 500
FILTERED_EXPORT_LIMIT = 1000


class ExportInvalid(ValueError):
    pass


class ExportRequest(BaseModel):
    """Omit receipt_ids to export all matching filters."""

    model_config = ConfigDict(extra="forbid")

    receipt_ids: Annotated[list[UUID] | None, Field(max_length=SELECTED_EXPORT_LIMIT)] = None
    filters: HistoryFilters = Field(default_factory=HistoryFilters)

    @model_validator(mode="after")
    def nonempty_selection(self):
        if self.receipt_ids is not None and not self.receipt_ids:
            raise ValueError("receipt_ids must contain at least one ID or be omitted")
        if self.receipt_ids and len(set(self.receipt_ids)) != len(self.receipt_ids):
            raise ValueError("receipt_ids must not contain duplicates")
        return self


def _ids_for_export(db, request: ExportRequest) -> list[str]:
    if request.receipt_ids is not None:
        ids = [str(value) for value in request.receipt_ids]
        placeholders = ",".join("?" for _ in ids)
        found = {
            row[0]
            for row in db.execute(
                f"SELECT receipt_id FROM receipts WHERE receipt_id IN ({placeholders})", ids
            )
        }
        missing = [value for value in ids if value not in found]
        if missing:
            raise ExportInvalid("One or more selected receipts no longer exist")
        return ids

    where, values = filter_clause(request.filters)
    rows = db.execute(
        HISTORY_CTE
        + "SELECT receipt_id FROM history"
        + where
        + " ORDER BY created_at DESC, receipt_id DESC LIMIT ?",
        values + (FILTERED_EXPORT_LIMIT + 1,),
    ).fetchall()
    if len(rows) > FILTERED_EXPORT_LIMIT:
        raise ExportInvalid(
            f"Filtered export exceeds {FILTERED_EXPORT_LIMIT} receipts; narrow the filters"
        )
    return [row[0] for row in rows]


def _records(db, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = db.execute(
        "SELECT r.*, c.result_json AS classification_json, "
        "v.result_json AS review_json, a.result_json AS amendment_json "
        "FROM receipts r LEFT JOIN classifications c USING(receipt_id) "
        "LEFT JOIN receipt_reviews v USING(receipt_id) "
        "LEFT JOIN receipt_amendments a ON a.receipt_id=r.receipt_id "
        "AND a.version=(SELECT max(a2.version) FROM receipt_amendments a2 "
        "WHERE a2.receipt_id=r.receipt_id) "
        f"WHERE r.receipt_id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id = {row["receipt_id"]: row for row in rows}
    records = []
    for receipt_id in ids:
        row = by_id[receipt_id]
        classification = json.loads(row["classification_json"]) if row["classification_json"] else None
        review = json.loads(row["review_json"]) if row["review_json"] else None
        amendment = json.loads(row["amendment_json"]) if row["amendment_json"] else None
        original = json.loads(row["extraction_json"]) if row["extraction_json"] else None
        if original is not None:
            original["line_items"] = [
                json.loads(item[0])
                for item in db.execute(
                    "SELECT item_json FROM line_items WHERE receipt_id=? ORDER BY position",
                    (receipt_id,),
                )
            ]
        if amendment:
            data, category, state = amendment["final_data"], amendment["category"], "AMENDED"
        elif review and review["decision"] == "APPROVED":
            data, category, state = review["final_data"], review["category"], "APPROVED"
        elif review:
            data = original
            category = (classification or {}).get("category")
            state = "REJECTED"
        else:
            data = original
            category = (classification or {}).get("category")
            state = (classification or {}).get("workflow_decision") or row["processing_status"]
        records.append(
            {
                "row": row,
                "data": data,
                "category": category,
                "state": state,
                "review": review,
                "amendment": amendment,
            }
        )
    return records


def _write_table(workbook, name: str, headers: list[str], rows: list[list[object]]) -> None:
    sheet = workbook.add_worksheet(name)
    header = workbook.add_format(
        {"bold": True, "bg_color": "#E8EEF8", "font_color": "#172033", "border": 1}
    )
    money = workbook.add_format({"num_format": "0.00"})
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, max(1, len(rows)), len(headers) - 1)
    for column, value in enumerate(headers):
        sheet.write(0, column, value, header)
    widths = [len(value) for value in headers]
    money_columns = {
        index
        for index, value in enumerate(headers)
        if any(word in value for word in ("Amount", "Subtotal", "Discount", "Tax", "Rounding", "Price", "Total"))
    }
    for row_index, row in enumerate(rows, start=1):
        for column, value in enumerate(row):
            if value is None:
                continue
            cell_format = money if column in money_columns and isinstance(value, (int, float)) else None
            sheet.write(row_index, column, value, cell_format)
            widths[column] = min(60, max(widths[column], len(str(value))))
    for column, width in enumerate(widths):
        sheet.set_column(column, column, max(10, min(60, width + 2)))


def build_export(store, request: ExportRequest) -> tuple[bytes, int]:
    """Return workbook bytes and receipt count; no connection spans response delivery."""
    with store.connect() as db:
        db.execute("BEGIN")
        ids = _ids_for_export(db, request)
        records = _records(db, ids)
        review_events = []
        amendment_events = []
        if ids:
            placeholders = ",".join("?" for _ in ids)
            review_events = [
                json.loads(row[0])
                for row in db.execute(
                    f"SELECT event_json FROM review_audit WHERE receipt_id IN ({placeholders})",
                    ids,
                )
            ]
            amendment_events = [
                json.loads(row[0])
                for row in db.execute(
                    f"SELECT event_json FROM amendment_audit WHERE receipt_id IN ({placeholders}) "
                    "ORDER BY receipt_id, version",
                    ids,
                )
            ]

    receipt_rows: list[list[object]] = []
    line_rows: list[list[object]] = []
    for record in records:
        row, data = record["row"], record["data"] or {}
        receipt_rows.append(
            [
                row["receipt_id"],
                data.get("vendor"),
                data.get("receipt_number"),
                data.get("date"),
                data.get("currency"),
                data.get("subtotal"),
                data.get("discount_amount"),
                data.get("tax_amount"),
                data.get("rounding_adjustment"),
                data.get("total_amount"),
                row["business_purpose"],
                record["category"],
                record["state"],
                row["created_at"],
                (record["amendment"] or record["review"] or {}).get("reviewer"),
            ]
        )
        for position, item in enumerate(data.get("line_items") or [], start=1):
            line_rows.append(
                [
                    row["receipt_id"], position, item.get("description"), item.get("quantity"),
                    item.get("unit_price"), item.get("discount_percent"),
                    item.get("discount_amount"), item.get("line_total"),
                ]
            )

    audit_rows = []
    for event in review_events:
        audit_rows.append(
            [event["receipt_id"], "REVIEW", event.get("review_version"), event.get("decision"),
             event.get("category"), event.get("reviewer"), event.get("reviewed_at"),
             event.get("note"), "; ".join(event.get("validation_issues") or []),
             event.get("override_reason")]
        )
    for event in amendment_events:
        audit_rows.append(
            [event["receipt_id"], "AMENDMENT", event.get("record_version"), "AMENDED",
             event.get("category"), event.get("reviewer"), event.get("amended_at"),
             event.get("reason"), "; ".join(event.get("validation_issues") or []),
             event.get("override_reason")]
        )

    output = BytesIO()
    workbook = xlsxwriter.Workbook(
        output,
        {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False},
    )
    workbook.set_properties({"title": "Receipt history export", "author": "Ledgerly"})
    _write_table(
        workbook,
        "Receipts",
        ["Receipt ID", "Vendor", "Receipt Number", "Receipt Date", "Currency", "Subtotal",
         "Receipt Discount", "Tax Amount", "Rounding", "Total Amount", "Business Purpose", "Category", "Status",
         "Uploaded At", "Latest Reviewer"],
        receipt_rows,
    )
    _write_table(
        workbook,
        "Line items",
        ["Receipt ID", "Line", "Description", "Quantity", "Unit Price", "Discount Percent",
         "Discount Amount", "Line Total"],
        line_rows,
    )
    _write_table(
        workbook,
        "Review audit",
        ["Receipt ID", "Event", "Version", "Decision", "Category", "Reviewer", "Timestamp",
         "Reason", "Validation Issues", "Override Reason"],
        audit_rows,
    )
    workbook.close()
    return output.getvalue(), len(records)
