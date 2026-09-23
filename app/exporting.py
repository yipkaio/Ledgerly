"""Bounded XLSX exports built from one immutable SQLite read snapshot."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import json
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
import xlsxwriter

from app.history import HISTORY_CTE, HistoryFilters, filter_clause


SELECTED_EXPORT_LIMIT = 500
FILTERED_EXPORT_LIMIT = 1000
ACCEPTED_STATES = frozenset({"AUTO_FILED", "APPROVED", "AMENDED"})


def _cents(value: object) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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
                f"SELECT receipt_id FROM receipts WHERE lifecycle_state='ACTIVE' AND receipt_id IN ({placeholders})", ids
            )
        }
        missing = [value for value in ids if value not in found]
        if missing:
            raise ExportInvalid("One or more selected receipts are deleted, voided, or no longer exist")
        return ids

    where, values = filter_clause(request.filters)
    where += (" AND " if where else " WHERE ") + "lifecycle_state='ACTIVE'"
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


def _formats(workbook) -> dict:
    return {
        "title": workbook.add_format({"bold": True, "font_size": 16, "font_color": "#17324D"}),
        "subtitle": workbook.add_format({"font_size": 9, "font_color": "#64748B", "italic": True}),
        "section": workbook.add_format({"bold": True, "font_color": "#17324D", "bottom": 2, "bottom_color": "#B8CBD8"}),
        "label": workbook.add_format({"bold": True, "font_color": "#526577", "font_size": 9}),
        "kpi": workbook.add_format({"bold": True, "font_size": 14, "font_color": "#17324D", "bg_color": "#EDF5F7", "border": 1, "border_color": "#D5E3E8"}),
        "money": workbook.add_format({"num_format": "#,##0.00;[Red](#,##0.00);-"}),
        # Source values are 10 for 10%, rather than Excel's 0.10 convention.
        "percentage_points": workbook.add_format({"num_format": '0.##"%"'}),
        "count": workbook.add_format({"num_format": "#,##0"}),
        "total_label": workbook.add_format({"bold": True, "top": 1, "top_color": "#94A3B8"}),
        "total_money": workbook.add_format({"bold": True, "top": 1, "top_color": "#94A3B8", "num_format": "#,##0.00;[Red](#,##0.00);-"}),
        "warning": workbook.add_format({"bg_color": "#FFF4E5", "font_color": "#9A3412"}),
        "issue": workbook.add_format({"bg_color": "#FDECEC", "font_color": "#9F1239"}),
        "good": workbook.add_format({"bg_color": "#ECFDF3", "font_color": "#166534"}),
    }


def _write_table_sheet(
    workbook,
    formats: dict,
    name: str,
    title: str,
    subtitle: str,
    headers: list[str],
    rows: list[list[object]],
    *,
    status_column: str | None = None,
    total_column: str | None = None,
) -> None:
    sheet = workbook.add_worksheet(name)
    sheet.hide_gridlines(2)
    sheet.set_landscape()
    sheet.fit_to_pages(1, 0)
    sheet.set_margins(0.35, 0.35, 0.5, 0.5)
    sheet.set_tab_color("#2A6F75" if name == "Receipts" else "#7BA7AE")
    sheet.write(1, 0, title, formats["title"])
    sheet.write(2, 0, subtitle, formats["subtitle"])
    table_row = 4
    last_column = len(headers) - 1
    widths = [len(value) for value in headers]
    money_headers = {"Subtotal", "Receipt Discount", "Tax Amount", "Rounding",
                     "Total Amount", "Unit Price", "Discount Amount", "Line Total"}
    if rows:
        sheet.add_table(
            table_row,
            0,
            table_row + len(rows),
            last_column,
            {
                "name": "Ledgerly" + "".join(character for character in name.title() if character.isalnum()),
                "style": "Table Style Medium 2",
                "columns": [{"header": value} for value in headers],
                "data": rows,
            },
        )
    else:
        empty_header = workbook.add_format({"bold": True, "bg_color": "#245C65", "font_color": "#FFFFFF", "border": 0})
        sheet.write_row(table_row, 0, headers, empty_header)
        sheet.autofilter(table_row, 0, table_row, last_column)
        sheet.write(table_row + 1, 0, "No records matched this export.", formats["subtitle"])
    for row in rows:
        for column, value in enumerate(row):
            if value is not None:
                widths[column] = min(60, max(widths[column], len(str(value))))
    for column, width in enumerate(widths):
        cell_format = (formats["percentage_points"] if headers[column] == "Discount Percent"
                       else formats["money"] if headers[column] in money_headers else None)
        sheet.set_column(column, column, max(11, min(45, width + 2)), cell_format)
    sheet.freeze_panes(table_row + 1, 0)
    sheet.repeat_rows(table_row)
    sheet.set_row(table_row, 24)
    if rows and status_column in headers:
        column = headers.index(status_column)
        start, end = table_row + 1, table_row + len(rows)
        letter = xlsxwriter.utility.xl_col_to_name(column)
        for value in ("APPROVED", "AUTO_FILED", "PAID", "MATCHED", "AMENDED"):
            sheet.conditional_format(start, column, end, column, {
                "type": "text", "criteria": "containing", "value": value, "format": formats["good"],
            })
        for value in ("REJECTED", "FAILED", "MISSING", "DUPLICATE", "PAYMENT_ISSUE", "NO_BANK_MATCH"):
            sheet.conditional_format(start, column, end, column, {
                "type": "text", "criteria": "containing", "value": value, "format": formats["issue"],
            })
    if rows and total_column in headers:
        column = headers.index(total_column)
        total_row = table_row + len(rows) + 2
        sheet.write(total_row, max(0, column - 1), "Total", formats["total_label"])
        total = sum(float(row[column] or 0) for row in rows)
        sheet.write_number(total_row, column, total, formats["total_money"])


def _write_receipt_overview(workbook, formats: dict, records: list[dict],
                            line_count: int, audit_count: int) -> None:
    sheet = workbook.add_worksheet("Overview")
    sheet.hide_gridlines(2)
    sheet.set_landscape()
    sheet.fit_to_pages(1, 1)
    sheet.set_margins(0.35, 0.35, 0.5, 0.5)
    sheet.set_tab_color("#17324D")
    sheet.set_column("A:A", 28)
    sheet.set_column("B:B", 30)
    sheet.set_column("C:F", 18)
    sheet.write("A2", "Receipt history", formats["title"])
    sheet.write("A3", f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Accepted spend excludes pending, rejected and failed records; currencies are never combined.", formats["subtitle"])
    kpis = [("Exported receipts", len(records)),
            ("Accepted receipts", sum(record["state"] in ACCEPTED_STATES for record in records)),
            ("Line items", line_count), ("Review events", audit_count),
            ("Currencies", len({(record["data"] or {}).get("currency") for record in records if (record["data"] or {}).get("currency")}))]
    for index, (label, value) in enumerate(kpis):
        column = index + 1
        sheet.write(5, column, label, formats["label"])
        sheet.write_number(6, column, value, formats["kpi"])

    currency_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "accepted": 0, "known": 0, "total_cents": 0})
    status_counts: dict[str, int] = defaultdict(int)
    category_totals: dict[tuple[str, str], int] = defaultdict(int)
    for record in records:
        data = record["data"] or {}
        currency = data.get("currency") or "Unknown"
        bucket = currency_totals[currency]
        bucket["count"] += 1
        status_counts[record["state"]] += 1
        if record["state"] in ACCEPTED_STATES:
            bucket["accepted"] += 1
            if data.get("total_amount") is not None:
                cents = _cents(data["total_amount"])
                bucket["known"] += 1
                bucket["total_cents"] += cents
                category_totals[(currency, record["category"] or "Uncategorized")] += cents

    row = 9
    sheet.write(row, 0, "Accepted spend by currency", formats["section"])
    headers = ["Currency", "Exported", "Accepted", "With known total", "Accepted spend"]
    rows = [[currency, values["count"], values["accepted"], values["known"], values["total_cents"] / 100]
            for currency, values in sorted(currency_totals.items())]
    if rows:
        sheet.add_table(row + 1, 0, row + 1 + len(rows), 4, {
            "name": "ReceiptCurrencyTotals", "style": "Table Style Medium 2",
            "columns": [{"header": value} for value in headers], "data": rows,
        })
        sheet.set_column("E:E", 18, formats["money"])
    else:
        sheet.write_row(row + 1, 0, headers)
        sheet.write(row + 2, 0, "No records matched this export.", formats["subtitle"])

    row += max(5, len(rows) + 4)
    sheet.write(row, 0, "Workflow status", formats["section"])
    status_rows = [[name, count] for name, count in sorted(status_counts.items())]
    if status_rows:
        sheet.add_table(row + 1, 0, row + 1 + len(status_rows), 1, {
            "name": "ReceiptStatusTotals", "style": "Table Style Medium 4",
            "columns": [{"header": "Status"}, {"header": "Receipts"}], "data": status_rows,
        })

    row += max(7, len(status_rows) + 4)
    sheet.write(row, 0, "Accepted spend by category and currency", formats["section"])
    category_rows = [[currency, category, cents / 100] for (currency, category), cents in
                     sorted(category_totals.items(), key=lambda item: (item[0][0], -item[1], item[0][1]))]
    if category_rows:
        sheet.add_table(row + 1, 0, row + 1 + len(category_rows), 2, {
            "name": "ReceiptCategoryTotals", "style": "Table Style Medium 2",
            "columns": [{"header": "Currency"}, {"header": "Category"}, {"header": "Accepted spend"}],
            "data": category_rows,
        })
        sheet.set_column("C:C", 16, formats["money"])
    sheet.freeze_panes(9, 0)


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
    formats = _formats(workbook)
    _write_receipt_overview(workbook, formats, records, len(line_rows), len(audit_rows))
    _write_table_sheet(
        workbook,
        formats,
        "Receipts",
        "Receipt details",
        "Latest recorded values for active receipts. Pending, rejected and failed amounts are excluded from accepted spend on Overview.",
        ["Receipt ID", "Vendor", "Receipt Number", "Receipt Date", "Currency", "Subtotal",
         "Receipt Discount", "Tax Amount", "Rounding", "Total Amount", "Business Purpose", "Category", "Status",
         "Uploaded At", "Latest Reviewer"],
        receipt_rows,
        status_column="Status",
    )
    _write_table_sheet(
        workbook,
        formats,
        "Line items",
        "Receipt line items",
        "Item-level values tied to the receipt identifiers in the Receipts sheet.",
        ["Receipt ID", "Line", "Description", "Quantity", "Unit Price", "Discount Percent",
         "Discount Amount", "Line Total"],
        line_rows,
    )
    _write_table_sheet(
        workbook,
        formats,
        "Review audit",
        "Review and amendment history",
        "Human decisions and corrections retained for audit review.",
        ["Receipt ID", "Event", "Version", "Decision", "Category", "Reviewer", "Timestamp",
         "Reason", "Validation Issues", "Override Reason"],
        audit_rows,
        status_column="Decision",
    )
    workbook.close()
    return output.getvalue(), len(records)
