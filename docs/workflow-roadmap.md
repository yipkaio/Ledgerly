# Workspace behavior and remaining work

## Available now

Navigation includes **Main dashboard**, **Monthly close**, **Upload receipt**,
**Pending reviews**, **Receipt history**, and **Deleted receipts**.
The dashboard is the default after connecting. It reads one authenticated database
snapshot with saved record counts, pending workload, accepted records and processing
issues. Refresh reloads the snapshot; there is no background polling.

Accepted totals include only human-approved and auto-filed receipts. Final human
amounts, currency, category and receipt date take precedence over original AI fields.
Rejected and pending records never contribute to these totals. Each currency has a
separate total, category chart and receipt-month trend. One inclusive receipt-date
range drives the total, count, categories and trend. The chart uses monthly
points through 24 months and yearly points for longer ranges; empty periods
are shown with zero recorded spend. Unknown amounts or
currencies are excluded and counted separately. Integer cents are summed before
formatting. Counts cover every saved attempt, including failures. These figures
are not payments, ledger postings or a deduplicated financial report.

History stays paginated at 20 records per page. Hover the **eye button** beside a
receipt for a compact preview anchored to that row, with a short opening delay and
fade animation. Click or press Enter/Space for keyboard and touch use. Escape,
the close button or clicking outside closes it. **Open full receipt** opens saved
evidence and a structured, read-only history record. Pending queue items expose the
review form; accepted history items require **Create amendment** before fields become
editable. Reduced-motion preferences disable the transition.

Previews request protected originals only when opened, with the active
development app key or production Firebase token in an authenticated header.
They do not rerun OCR or LLM extraction. Previews never scroll: vendor title and
amount stay in a fixed header and the entire image scales to fit the remaining
space. Card height and side are chosen on opening rather than recalculated from
image dimensions. Only one card is open at a time. Animation changes opacity only;
scrolling the list or resizing dismisses the preview. Images
stay mounted throughout the closing fade; afterward unfinished reads are aborted
and blob URLs revoked. Images are not written to browser storage or preloaded for every row.
The original endpoint can transfer up to the configured upload limit; bounded
server-generated thumbnails would further reduce transfers for large images.

## Duplicate receipts (implemented)

The server hashes each validated upload while streaming it to disk. An exact binary
match returns 409 with `existing_receipt_id` before OCR or gateway calls. A unique
database index also closes the concurrent-upload race.

After extraction, potential matches use vendor, receipt number, date, currency and
payable total. A new photo or recompressed image has a different file hash and needs
this second check. It cannot prevent the initial extraction charge because the
identity fields are not known before extraction. Legitimate recurring invoices with
different dates or numbers are not duplicates merely because vendor and amount repeat.
The candidate is sent to review and links the prior receipt ID. A dedicated
confirmed/not-duplicate disposition remains a later refinement.

## Editing filed receipts: audited amendments (implemented)

Auto-filed and approved receipts can be corrected by first choosing **Create
amendment**, then **Save amendment**, or through
`POST /receipts/{id}/amendments`. Every change requires reviewer, reason, evidence
confirmation, current `record_version`, an idempotent request UUID, complete
validated fields and category. Original OCR, AI extraction, review and every earlier
amendment remain immutable. Stale concurrent edits return 409. Detail, history and
dashboard use the newest effective version. Rejected/pending/failed receipts cannot
be amended; reversal is a separate future transition. A shared app key still does
not establish reviewer roles.

## Filtered history and selected Excel export (implemented)

History supports server-side vendor/receipt search, effective category, currency,
workflow status and inclusive receipt-date filters. Filters drive pagination and
**Export filtered**. Row and select-page checkboxes preserve explicit IDs across
pages for **Export selected**; changing filters clears selection to prevent hidden
rows from being exported accidentally. Selection never implies bulk approval.

The authenticated server generates:

| Sheet | Contents |
| --- | --- |
| Overview | Exported and accepted counts, accepted spend separated by currency and category, and status counts |
| Receipts | Vendor, receipt/date, currency, amounts, tax/rounding, purpose, effective category, status and reviewer |
| Line items | Receipt ID, description, quantity, prices, optional discounts and totals |
| Review audit | Decisions/amendments, reviewer, timestamps and reasons |

The server uses the same effective-value rules as the dashboard and one SQLite read
snapshot. Selected exports are capped at 500 receipts and filtered exports at 1,000.
Unknown values remain blank, formula-like strings stay text, and downloads are
authenticated and non-cacheable. See [the export guide](export.md).

## PDFs (implemented)

Uploads accept emailed or scanned PDFs through a separately tested path. The server
checks the PDF signature, keeps the original behind authentication, rejects
encrypted/malformed files and defaults to three pages and 5 MB. Usable embedded
text is extracted per page; pages without it are rendered under time, dimension and
pixel limits and sent through the selected OCR engine. Only the resulting text goes
to the LLM gateway. A bounded first-page PNG supports authenticated previews.
One multi-page document represents one receipt; multiple invoices must be split.

## Further usability priorities

1. Receipt zoom/rotation and **Review next** to reduce repetitive navigation.
2. Stage progress and failure recovery that reuses saved OCR instead of charging
   for a whole repeated pipeline. Avoid invented progress percentages while the
   current upload remains one synchronous request.
3. Individual authentication and reviewer roles before public multi-user access.
4. Friendly empty states, saved-filter links without credentials and accessible
   action notifications. Preserve existing unsaved-change warnings, confirmation
   dialogs, retained error drafts and safe review retries.

Duplicate prevention, audited amendments, filtered history, Excel export and PDF
ingestion are now implemented. Dashboard and preview changes do not
create AWS resources or automatically change the deployed instance.

The current SQLite schema is v9, with monthly review events in addition to
receipt, statement and payment history. See [the maintenance review](maintenance-review.md)
for code cleanup candidates that require their own behavior and migration checks.
