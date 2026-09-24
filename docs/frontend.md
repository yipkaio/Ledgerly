# Receipt workspace

The React + TypeScript frontend lives in `frontend/`. Vite builds it at `/ui/`;
FastAPI serves that build in Docker on the same origin as the API. The UI works
with API documentation disabled. No additional public port or CORS rule is needed.

## Use the Docker build locally

In Windows PowerShell, from the repository root:

```powershell
docker compose build api
docker compose up -d --wait --wait-timeout 120
```

Open http://127.0.0.1:8000/ui/ and enter the `APP_API_KEY` configured in your local
`.env`. Use the app key, never the gateway key. Keep Docker Desktop running while
using this local container. An existing Uvicorn server on port 8000 must be stopped
first. Docker preserves uploads, SQLite data, and OCR caches in the existing volumes.

## Develop the frontend

Install Node.js 24 LTS, then in a second PowerShell window:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173/ui/. Run the backend separately on localhost port 8000
using your Python environment and `.env`. Vite proxies the `/auth`, `/ai`,
`/bank-statements`, `/dashboard`, `/receipts`, `/reconciliation` and `/reviews`
API paths to that backend. The same server key applies, and this uses your local
database.

To build and check the frontend:

```powershell
npm run build
npm run lint
npx playwright install chromium
npm test
```

Browser tests mock API and image responses; they never run OCR or make gateway
calls. The Python suite tests actual image endpoints and review persistence.
`npm run build` checks TypeScript before bundling. Do not commit node_modules,
dist, browser test reports, local data, or credentials.

## Review a receipt

After connecting, **Main dashboard** shows a focused accepted-spend total, actionable
metrics, a trend, category ranking, workflow distribution, and attention counts.
The date range beside the saved reporting currency offers quick latest-month,
latest-three-months, latest-receipt-year, and all-time selections, plus a custom inclusive
receipt-date range. It updates the accepted total, accepted count, categories, and
monthly trend together. Ranges longer than 24 months show yearly points. Click
**View this date range** to see the same dated accepted receipts in history.
Undated accepted records remain accessible in Receipt history but cannot be included
in a dated total. Pending reviews and overall workflow counts describe the entire
workspace. Native currency totals remain separate when conversion is unavailable.
Navigation then offers **Upload receipt**, **Pending reviews**, and **Receipt history**. Hover the
eye button beside a history row for
an animated private preview, or use click/Enter on keyboard and touch devices.
See [workflow behavior and planned features](workflow-roadmap.md) for implemented
duplicate/amendment controls, filtered Excel export, and the PDF milestone.

Previews do not scroll. A fixed header keeps the vendor title, amount and close
button visible; long titles are shortened visually, with the full title available
on hover and to screen readers. The complete receipt image fits beneath the header.
Card height and placement are chosen when opening, and animation only changes
opacity. One preview is open at a time, including previews opened by click or
keyboard. Scrolling the history list or resizing the window dismisses the card.
The image stays mounted through the closing fade, then requests and image URLs
are released. Use **Open full receipt** for detailed inspection.

History filters run on the server and use the latest approved or amended values.
Search accepts vendor, receipt number, or receipt ID. Category, currency, effective
workflow status, and inclusive receipt-date ranges can be combined. Click **Apply
filters**; pagination and **Export filtered** then use the same scope. Changing or
clearing filters also clears selected IDs.

Use row checkboxes or **Select all receipts on this page** to build an explicit
selection across pages. **Export selected** downloads only those IDs. The selected
count stays visible, and **Clear selection** never changes receipt decisions. See
[History filters and Excel export](export.md) for limits and workbook fields.

1. Sign in with the pre-approved Firebase email/password account in production.
   In local `api_key` mode, enter the configured app key. The workspace is
   shared; the reviewer name remains a self-reported audit label.
2. Choose **Upload receipt**. Select a JPEG, PNG, or PDF up to 5 MB. PDFs can have
   up to three pages and represent one receipt. Enter an optional
   business purpose, then click **Upload and process** once. Processing may consume
   gateway credits. On a lost response, check history before uploading again. An
   exact duplicate returns the existing receipt ID without rerunning OCR/LLM.
3. Choose **Pending reviews** to make a decision. **Receipt history** opens a
   read-only, structured receipt summary; it never puts finalized fields directly
   into edit mode. Both lists are paginated in groups of 20. A missing vendor or
   amount means processing did not extract it; inspect the saved record for errors.
4. Compare the **Original receipt** with all fields, items, discounts, tax, and
   rounding. Receipt discount is the invoice-wide amount applied after subtotal
   and before tax; line-item discounts remain attached to individual items. The
   original image loads only when a receipt or preview is opened.
   Open full size when needed. Raw OCR remains stored for traceability and API
   diagnostics but is intentionally not shown in the normal review interface.
   Read both extraction and classification review reasons.
5. Correct verified fields. Empty optional fields remain null. Currency, vendor,
   date and total are required for approval. Receipt-level and line-item discount
   fields are optional, and zero is not a substitute for unknown. Verify that
   subtotal minus receipt discount plus tax and rounding reconciles to the total.
   Supported review currencies are SGD, MYR,
   USD, EUR, GBP and AUD. Monetary fields accept two decimal places.
6. Choose the justified category and supply your name and decision reason. Record
   confirmed business purpose in the reason; the review does not change the original
   purpose. Check evidence confirmation only after inspection. If uncertain, leave
   the receipt pending. Rejection is a final exclusion, not a request for information.
7. Click **Approve receipt** or **Reject receipt** and read the confirmation dialog.
   Approval sends the complete corrected extraction. Rejection omits correction
   and category fields. The UI creates the request UUID and copies the saved version.
8. Confirm once. The record reloads after saving; inspect **Review audit**. Its
   timeline shows decision, reviewer, timestamp, evidence confirmation, category,
   and deterministic before/after field changes without exposing a raw JSON dump.
   The original AI evidence stays intact and the human decision is final. Approved
   data and human status appear in history; finalized receipts leave the queue.
9. Open an auto-filed or approved receipt in history and choose **Create amendment**
   to enter correction mode. **Save amendment** creates a new effective version;
   enter a specific reason and re-confirm the evidence. **Cancel amendment** returns
   to the saved read-only record. Earlier versions stay in the audit and stale
   concurrent edits are rejected.

For validation errors, correct the identified fields; edits are retained. An
explicit override explanation is only for an evidence-supported remaining amount
issue; it cannot bypass schema, missing-field, currency, or placeholder checks.
A stale/conflicting request blocks further decisions until the saved record is
reloaded. On an uncertain response, edits freeze and **Retry same change** sends
exactly the same UUID and payload. **Reload saved record** checks what was saved
and discards local edits. Reloading, disconnecting or leaving the receipt also
loses unsaved edits. Navigation, disconnecting, and browser reloads warn while a
review has unsaved changes. Choosing to discard or reloading the saved record
clears the local draft. Network reads and decision requests time out after 30
seconds; uploads allow up to 330 seconds and are never retried automatically.

A missing/unreadable original image blocks decisions in the UI. Earlier OCR failures
may have cleaned up the image. Check the retained original separately through the
manual review process if needed; do not claim evidence confirmation without inspection.
Review actions make no LLM calls and do not create new vendor mappings.

## Import a monthly bank statement

Open **Monthly close** and choose **Upload statement**. A normalized UTF-8 CSV can
still be imported directly. A PDF is read first and shown as a debit-row preview;
the original is retained only after the user checks the rows and confirms the
evidence. Encrypted PDFs accept a password for that request only. Deterministic
parsing stays inside Ledgerly. The separately labelled AI fallback is opt-in
because statement text can contain company and counterparty information and the
gateway call may consume credits. A detected balance mismatch blocks import.

After import, choose **View source** to keep the retained PDF or CSV in a
read-only side panel while reviewing all normalized debits. CSV content is
displayed as plain text, never interpreted as HTML. Matched and unmatched
accepted receipts are listed in the same monthly workspace and can be opened in
Ledgerly to inspect their retained evidence, effective values, and audit history.
Downloaded receipt-history and monthly-close workbooks start with a summary,
keep currencies separate, include static totals and status breakdowns, and use
formatted, filterable detail tables with one-page-wide print settings.

## Access the AWS container privately

For production updates, follow [Docker deployment](docker.md) and
[authentication](authentication.md). The public browser uses HTTPS with the
pre-approved Firebase account; the API stays private behind Caddy. A localhost
SSH tunnel can be used for private operational inspection. Local and AWS
databases and keys are separate; rebuilding locally does not update Lightsail.

## Security and accessibility

The development app key and production Firebase ID token stay in React memory;
disconnect/reload clears them. They are not placed in browser storage, URLs,
build variables or source files. The browser receives no gateway credentials.
Data/image requests remain authenticated and
responses use `Cache-Control: no-store`. The public static shell contains no receipt
or secret data. Production sets content security, no-sniff, and referrer headers.
Blob image/PDF URLs are revoked on leaving a receipt. Production uses HTTPS.
The single approved account, trusted integration key holders and server
administrators can access workspace data. Separate reviewer roles, account
isolation and audited reopening are future work.

Labels, focus outlines, a skip link, semantic tables, native number inputs, Radix
select keyboard behavior, and focus-trapped confirmation dialogs support keyboard
review. Charts include accessible names and exact values, never rely on color alone,
and use no additional chart runtime. At small sizes the two review columns stack
and tables scroll within their own container. Status uses text as well as color.
The review bundle and receipt image load on demand. Only one page of history is
fetched at a time.

## Component sources

Scaffold: [Vite React + TypeScript](https://vite.dev/guide/).
Styling: [Tailwind's Vite integration](https://tailwindcss.com/docs/installation/using-vite).
Components: [shadcn/ui Vite setup](https://ui.shadcn.com/docs/installation/vite).
The UI components are copied from shadcn's `new-york-v4` registry in
`shadcn-ui/ui/apps/v4/registry/new-york-v4/ui`, with import paths adjusted locally.
They remain editable source in `src/components/ui`, using Radix primitives and
Tailwind tokens. See `frontend/THIRD_PARTY_NOTICES.md` for source attribution.
# Deleted receipts and protected records

Use the **Deleted receipts** tab to inspect restore deadlines and open a record for restoration. Pending, failed and rejected receipts can be moved there from the receipt's management panel. Approved, auto-filed and amended records instead offer **Void receipt**, with a mandatory reason. Voided records remain read-only in history, show a neutral status badge, and cannot be selected for export. Confirmation dialogs explain the effect and preserve an identical request for retries after a connection failure. Unsaved review edits must be saved or discarded first. See [retention rules](receipt-lifecycle.md).
