# Workspace feedback and next features

## Available now

Navigation follows **Main dashboard → Upload receipt → Pending reviews → Receipt history**.
The dashboard is the default after connecting. It reads one authenticated database
snapshot with saved record counts, pending workload, accepted records and processing
issues. Refresh reloads the snapshot; there is no background polling.

Accepted totals include only human-approved and auto-filed receipts. Final human
amounts, currency, category and receipt date take precedence over original AI fields.
Rejected and pending records never contribute to these totals. Each currency has a
separate total, category chart and receipt-month trend. Trends show the latest 12
months with dated accepted records; empty months are omitted. Unknown amounts or
currencies are excluded and counted separately. Integer cents are summed before
formatting. Counts cover every saved attempt, including failures. These figures
are not payments, ledger postings or a deduplicated financial report.

History stays paginated at 20 records per page. Hover the **eye button** beside a
receipt for a compact preview anchored to that row, with a short opening delay and
fade animation. Click or press Enter/Space for keyboard and touch use. Escape,
the close button or clicking outside closes it. **Open full receipt** opens the saved
evidence and review form. Reduced-motion preferences disable the transition.

Previews request protected originals only when opened, with the app key in a header.
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

Auto-filed and approved receipts can be corrected through **Save amendment** or
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

The authenticated server should generate:

| Sheet | Contents |
| --- | --- |
| Receipts | Vendor, receipt/date, currency, amounts, tax/rounding, purpose, effective category, status and reviewer |
| Line items | Receipt ID, description, quantity, prices, optional discounts and totals |
| Review audit | Decisions/amendments, reviewer, timestamps and reasons |

The server uses the same effective-value rules as the dashboard and one SQLite read
snapshot. Selected exports are capped at 500 receipts and filtered exports at 1,000.
Unknown values remain blank, formula-like strings stay text, and downloads are
authenticated and non-cacheable. See [the export guide](export.md).

## PDFs

PDF support is useful for emailed invoices and scanned receipts. Current uploads
accept JPEG/PNG only; adding a PDF option to the browser input is insufficient.

Add a separately tested path: extract usable embedded text, otherwise render pages
and run OCR. Retain the original PDF and protected page previews. Send text to the
gateway. Start with 5 MB and up to 3 pages, reject encrypted/malformed documents,
and bound rendering time, dimensions and memory. Initially one multi-page document
should represent one receipt; splitting multiple invoices should be explicit.

## Further usability priorities

1. Receipt zoom/rotation and **Review next** to reduce repetitive navigation.
2. Stage progress and failure recovery that reuses saved OCR instead of charging
   for a whole repeated pipeline. Avoid invented progress percentages while the
   current upload remains one synchronous request.
3. Individual authentication and reviewer roles before public multi-user access.
4. Friendly empty states, saved-filter links without credentials and accessible
   action notifications. Preserve existing unsaved-change warnings, confirmation
   dialogs, retained error drafts and safe review retries.

Duplicate prevention, audited amendments, filtered history and Excel export are now
implemented. PDF ingestion is next. Dashboard and preview changes do not
create AWS resources or automatically change the deployed instance.
