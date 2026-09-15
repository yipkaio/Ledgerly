# History filters and Excel export

Both features are available in **Receipt history** under `/ui/` and through the
authenticated API. They are read-only: no OCR, gateway calls, approvals, amendments,
vendor-rule changes, or accounting postings occur.

## Filter history

The UI can combine vendor/receipt/ID search with category, currency, effective
status, and an inclusive receipt-date range. Click **Apply filters** before paging
or exporting. The API equivalent is:

```http
GET /receipts?query=R000027830&category=Office%20Supplies&currency=MYR&state=AMENDED&date_from=2019-01-01&date_to=2019-12-31&limit=20&offset=0
```

Supported effective states are `AUTO_FILED`, `APPROVED`, `AMENDED`, `REJECTED`,
`REVIEW_QUEUE`, `PROCESSING`, and `FAILED`. Search treats `%` and `_` literally,
not as database wildcards. Date filters use the receipt date, not upload time.
Approved or amended values take precedence over original AI fields.

## Select and export

- Select individual rows or the current page. IDs stay selected while paging.
- Changing or clearing filters clears the selection deliberately.
- **Export selected** exports 1–500 explicit IDs, even across pages.
- **Export filtered** exports the complete current filter result, up to 1,000 rows.
- A 422 response means the request is invalid, a selected record disappeared, or
  the filtered result needs narrower filters.

Selected API request:

```json
{
  "receipt_ids": ["1d898e3a-66fa-4651-bb71-ca85d0a7770f"]
}
```

Filtered API request (omit `receipt_ids`):

```json
{
  "filters": {
    "currency": "MYR",
    "state": "APPROVED",
    "date_from": "2026-01-01",
    "date_to": "2026-12-31"
  }
}
```

The private `.xlsx` is generated from one SQLite read snapshot:

| Sheet | Contents |
| --- | --- |
| Receipts | Effective vendor, receipt/date, currency, totals, purpose, category, status, upload time, latest reviewer |
| Line items | Receipt ID, order, description, quantity, unit price, nullable discounts, line total |
| Review audit | Approval/rejection/amendment type, version, category, reviewer, timestamp, reason, validation and override |

Unknown values remain blank and currencies are never combined. Text beginning with
spreadsheet formula characters remains plain text. The response uses `no-store`;
the downloaded file itself is sensitive and belongs only in approved storage.
