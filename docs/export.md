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

Supported effective states are `AUTO_FILED`, `APPROVED`, `AMENDED`, `VOIDED`,
`REJECTED`, `REVIEW_QUEUE`, `PROCESSING`, and `FAILED`. Deleted records are
available through the separate Deleted receipts view. Search treats `%` and `_` literally,
not as database wildcards. Date filters use the receipt date, not upload time.
Approved or amended values take precedence over original AI fields.

## Select and export

- Select individual rows or the current page. IDs stay selected while paging.
- Changing or clearing filters clears the selection deliberately.
- **Export selected** exports 1–500 explicit IDs, even across pages.
- **Export filtered** exports the complete current filter result, up to 1,000 rows.
- A 422 response means the request is invalid, a selected record disappeared, or
  the filtered result needs narrower filters.

Send these bodies to `POST /receipts/export`. Selected API request:

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
| Overview | Exported and accepted counts; accepted spend by currency and category; workflow status counts. Pending, rejected and failed values are excluded from spend. |
| Receipts | Effective vendor, receipt/date, currency, subtotal, receipt discount, tax, totals, purpose, category, status, upload time, latest reviewer |
| Line items | Receipt ID, order, description, quantity, unit price, nullable discounts, line total. Discount percentages display as percentage points (for example `10` appears as `10%`). |
| Review audit | Approval/rejection/amendment type, version, category, reviewer, timestamp, reason, validation and override |

Detail rows retain the latest extracted or reviewed values even for unaccepted
receipts, but only `AUTO_FILED`, `APPROVED` and `AMENDED` contribute to accepted
spend. **With known total** counts accepted receipts with a recorded amount;
missing totals do not silently become zero spend. Overview sums integer cents
per currency before displaying monetary totals. Unknown values remain blank and
currencies are never combined. Text beginning with
spreadsheet formula characters remains plain text. Summary and detail sheets use
filterable tables, frozen headers, status highlighting and one-page-wide print
settings. The response uses `no-store`; the downloaded file itself is sensitive
and belongs only in approved storage.
# Lifecycle exclusions

Deleted and voided receipts are excluded from filtered exports. Explicit selections containing either are rejected with a clear error instead of silently exporting an incomplete selection. Existing downloaded workbooks are not modified. Voided evidence remains accessible in receipt history; deleted evidence remains accessible until its retention deadline and cleanup.
