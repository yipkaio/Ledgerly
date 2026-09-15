"""Validated history filters and effective-value SQL shared by lists and exports."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.classification import ExpenseCategory


HistoryState = Literal[
    "AUTO_FILED",
    "APPROVED",
    "AMENDED",
    "REJECTED",
    "REVIEW_QUEUE",
    "PROCESSING",
    "FAILED",
]


class HistoryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str | None = Field(default=None, max_length=100)
    vendor: str | None = Field(default=None, max_length=100)
    category: ExpenseCategory | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    state: HistoryState | None = None
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        self.query = self.query or None
        self.vendor = self.vendor or None
        return self


HISTORY_CTE = """WITH history AS (
 SELECT r.receipt_id, r.content_type, r.size_bytes, r.business_purpose,
 r.processing_status, r.created_at, r.updated_at, c.decision,
 COALESCE(json_extract(a.result_json, '$.final_data.vendor'),
          json_extract(v.result_json, '$.final_data.vendor'),
          json_extract(r.extraction_json, '$.vendor')) AS vendor,
 COALESCE(json_extract(a.result_json, '$.final_data.receipt_number'),
          json_extract(v.result_json, '$.final_data.receipt_number'),
          json_extract(r.extraction_json, '$.receipt_number')) AS receipt_number,
 COALESCE(json_extract(a.result_json, '$.final_data.date'),
          json_extract(v.result_json, '$.final_data.date'),
          json_extract(r.extraction_json, '$.date')) AS receipt_date,
 COALESCE(json_extract(a.result_json, '$.final_data.total_amount'),
          json_extract(v.result_json, '$.final_data.total_amount'),
          json_extract(r.extraction_json, '$.total_amount')) AS total_amount,
 COALESCE(json_extract(a.result_json, '$.final_data.currency'),
          json_extract(v.result_json, '$.final_data.currency'),
          json_extract(r.extraction_json, '$.currency')) AS currency,
 COALESCE(json_extract(a.result_json, '$.category'),
          json_extract(v.result_json, '$.category'),
          json_extract(c.result_json, '$.category')) AS category,
 CASE WHEN a.version IS NOT NULL THEN 'AMENDED'
      WHEN v.result_json IS NOT NULL THEN json_extract(v.result_json, '$.decision')
      ELSE COALESCE(c.decision, r.processing_status) END AS workflow_state,
 CASE WHEN a.version IS NOT NULL THEN 'AMENDED'
      ELSE json_extract(v.result_json, '$.decision') END AS review_decision
 FROM receipts r
 LEFT JOIN classifications c USING(receipt_id)
 LEFT JOIN receipt_reviews v USING(receipt_id)
 LEFT JOIN receipt_amendments a ON a.receipt_id=r.receipt_id
  AND a.version=(SELECT max(a2.version) FROM receipt_amendments a2
                 WHERE a2.receipt_id=r.receipt_id)
) """


HISTORY_COLUMNS = (
    "receipt_id, content_type, size_bytes, business_purpose, processing_status, "
    "created_at, updated_at, decision, vendor, receipt_number, receipt_date, "
    "total_amount, currency, category, workflow_state, review_decision"
)


def _contains(value: str) -> str:
    escaped = value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def filter_clause(filters: HistoryFilters) -> tuple[str, tuple]:
    clauses: list[str] = []
    values: list[object] = []
    if filters.query:
        pattern = _contains(filters.query)
        clauses.append(
            "(lower(COALESCE(vendor,'')) LIKE ? ESCAPE '\\' OR "
            "lower(COALESCE(receipt_number,'')) LIKE ? ESCAPE '\\' OR "
            "lower(receipt_id) LIKE ? ESCAPE '\\')"
        )
        values.extend((pattern, pattern, pattern))
    if filters.vendor:
        clauses.append("lower(COALESCE(vendor,'')) LIKE ? ESCAPE '\\'")
        values.append(_contains(filters.vendor))
    if filters.category:
        clauses.append("category=?")
        values.append(filters.category.value)
    if filters.currency:
        clauses.append("currency=?")
        values.append(filters.currency)
    if filters.state:
        clauses.append("workflow_state=?")
        values.append(filters.state)
    if filters.date_from:
        clauses.append("receipt_date>=?")
        values.append(filters.date_from.isoformat())
    if filters.date_to:
        clauses.append("receipt_date<=?")
        values.append(filters.date_to.isoformat())
    return (" WHERE " + " AND ".join(clauses) if clauses else "", tuple(values))
