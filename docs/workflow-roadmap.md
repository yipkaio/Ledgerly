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

## Duplicate receipts: next correctness milestone

Every current upload creates a new ID and runs OCR/extraction again. Identical
uploads can consume gateway credits again and create duplicate expenses. The
dashboard reports those records individually. Review request UUIDs protect decision
retries; they do not deduplicate uploads.

Planned behavior:

- Hash validated file bytes and reserve that hash transactionally before paid
  processing. Concurrent identical uploads must link to the existing record rather
  than both starting gateway calls. Display its saved status, including processing
  or failure. Retrying a failed stage must be explicit.
- After extraction, flag potential matches using vendor, receipt number, date,
  currency and payable total. A new photo/recompressed image has a different file
  hash and needs this second check. This check cannot prevent its initial extraction
  charge because the match fields are not yet known before extraction.
- Show both records for confirmation; legitimate recurring invoices with different
  dates/numbers are not duplicates merely because vendor and amount repeat.
- Record a duplicate disposition while retaining evidence and history. Change the
  business purpose through an amendment rather than another upload.

## Editing filed receipts: audited amendments

Bookkeepers should be able to correct an auto-filed or approved receipt. The current
endpoint accepts one final decision for a queued receipt; filed/finalized records
remain read-only. Removing its pending check alone would break the existing model.

Add **Amend receipt** with reviewer, reason, current version, idempotent request ID,
and validated final fields/category. Preserve original OCR, AI extraction, earlier
human decisions and every amendment. Reject stale versions when two people edit the
same record. Lists, dashboard and exports must read the latest effective version.
Reopening/rejection reversals need recorded transitions. A shared app key does not
establish reviewer roles; individual authentication remains separate future work.

## Selected Excel export

Bulk selection and `.xlsx` download are not implemented. Add row checkboxes, a
select-page control, selected count and clear-selection action. Preserve receipt IDs
across pages and state whether an export covers selected records or all filtered
results. Selection must not imply bulk approval.

The authenticated server should generate:

| Sheet | Contents |
| --- | --- |
| Receipts | Vendor, receipt/date, currency, amounts, tax/rounding, purpose, effective category, status and reviewer |
| Line items | Receipt ID, description, quantity, prices, optional discounts and totals |
| Review audit | Decisions/amendments, reviewer, timestamps and reasons |

Use the same effective-value rules as the dashboard, receipt IDs for joins and
separate currency totals. Unknown values remain blank. Export a consistent snapshot,
bound the selection/file size, treat descriptions as text instead of spreadsheet
formulas, and send private non-cacheable downloads.

## PDFs

PDF support is useful for emailed invoices and scanned receipts. Current uploads
accept JPEG/PNG only; adding a PDF option to the browser input is insufficient.

Add a separately tested path: extract usable embedded text, otherwise render pages
and run OCR. Retain the original PDF and protected page previews. Send text to the
gateway. Start with 5 MB and up to 3 pages, reject encrypted/malformed documents,
and bound rendering time, dimensions and memory. Initially one multi-page document
should represent one receipt; splitting multiple invoices should be explicit.

## Further usability priorities

1. Server-side vendor/date/category/status/currency search and filters, connected to
   pagination and export selection. Issue cards currently open all history; focused
   failed/processing filters should follow.
2. Receipt zoom/rotation and **Review next** to reduce repetitive navigation.
3. Stage progress and failure recovery that reuses saved OCR instead of charging
   for a whole repeated pipeline. Avoid invented progress percentages while the
   current upload remains one synchronous request.
4. Individual authentication and reviewer roles before public multi-user access.
5. Friendly empty states, saved-filter links without credentials and accessible
   action notifications. Preserve existing unsaved-change warnings, confirmation
   dialogs, retained error drafts and safe review retries.

Recommended order: duplicate prevention and audited amendments, then filtered
history and Excel export, followed by PDFs. Dashboard and preview changes do not
create AWS resources or automatically change the deployed instance.
