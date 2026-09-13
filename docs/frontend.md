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
using your Python environment and `.env`. Vite proxies `/receipts`, `/reviews` and `/dashboard`
to that backend, so the same server key applies. This uses your local database.

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

After connecting, **Main dashboard** shows saved counts and accepted expense charts
separately for each currency. Navigation then offers **Upload receipt**, **Pending
reviews**, and **Receipt history**. Hover the eye button beside a history row for
an animated private preview, or use click/Enter on keyboard and touch devices.
See [workflow behavior and planned features](workflow-roadmap.md) for duplicate
uploads, audited amendments, selected Excel export and PDFs.

1. Connect with the chosen server's app key. All key holders share one workspace;
   this is not individual user authentication.
2. Choose **Upload receipt**. Select a JPEG or PNG up to 5 MB. Enter an optional
   business purpose, then click **Upload and process** once. Processing may consume
   gateway credits. On a lost response, check history before uploading again.
3. Open the saved receipt, or choose **Pending reviews**. History and pending lists
   are paginated in groups of 20. A missing vendor or amount means processing did
   not extract it; inspect the saved record for errors.
4. Compare the **Original receipt** with all fields, items, discounts, tax, and
   rounding. The original image loads only when a receipt or preview is opened. Open full size
   when needed. Read both extraction and classification review reasons.
5. Correct verified fields. Empty optional fields remain null. Currency, vendor,
   date and total are required for approval. Discount fields are optional, and zero
   is not a substitute for unknown. Supported review currencies are SGD, MYR,
   USD, EUR, GBP and AUD. Monetary fields accept two decimal places.
6. Choose the justified category and supply your name and decision reason. Record
   confirmed business purpose in the reason; the review does not change the original
   purpose. Check evidence confirmation only after inspection. If uncertain, leave
   the receipt pending. Rejection is a final exclusion, not a request for information.
7. Click **Approve receipt** or **Reject receipt** and read the confirmation dialog.
   Approval sends the complete corrected extraction. Rejection omits correction
   and category fields. The UI creates the request UUID and copies the saved version.
8. Confirm once. The record reloads after saving; inspect **Review audit**. The
   original AI evidence stays intact and the human decision is final. Approved data
   and human status appear in history; finalized receipts leave the pending queue.

For validation errors, correct the identified fields; edits are retained. An
explicit override explanation is only for an evidence-supported remaining amount
issue; it cannot bypass schema, missing-field, currency, or placeholder checks.
A stale/conflicting request blocks further decisions until the saved record is
reloaded. On an uncertain response, edits freeze and **Retry same decision** sends
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

## Access the AWS container privately

After you have reviewed this commit locally, pull and rebuild on Lightsail using
the existing deployment procedure. Do not open port 8000 to the internet. Keep
your Windows SSH tunnel from port 18000 to the instance's localhost port 8000 open,
then visit http://127.0.0.1:18000/ui/. Enter the AWS server's APP_API_KEY. Local and
AWS databases and keys are separate. This commit does not update your instance.

## Security and accessibility

The app key is kept only in React memory; disconnect/reload clears it. It is never
stored in browser storage, URLs, build variables, or source files. The browser
receives no gateway credentials. Data/image requests remain authenticated and
responses use `Cache-Control: no-store`. The public static shell contains no receipt
or secret data. Production sets content security, no-sniff, and referrer headers.
Blob image URLs are revoked on leaving a receipt. Use HTTPS for any future public
host; retain the SSH tunnel for the current private setup. Trusted key holders and
server administrators can access workspace data. Verified user identity, role
permissions, account isolation, and audited reopening are future work.

Labels, focus outlines, a skip link, semantic tables, native number inputs, Radix
select keyboard behavior, and focus-trapped confirmation dialogs support keyboard
review. At small sizes the two review columns stack and tables scroll within their
own container. Status uses text as well as color. The review bundle and receipt
image load on demand. Only one page of history is fetched at a time.

## Component sources

Scaffold: [Vite React + TypeScript](https://vite.dev/guide/).
Styling: [Tailwind's Vite integration](https://tailwindcss.com/docs/installation/using-vite).
Components: [shadcn/ui Vite setup](https://ui.shadcn.com/docs/installation/vite).
The UI components are copied from shadcn's `new-york-v4` registry in
`shadcn-ui/ui/apps/v4/registry/new-york-v4/ui`, with import paths adjusted locally.
They remain editable source in `src/components/ui`, using Radix primitives and
Tailwind tokens. See `frontend/THIRD_PARTY_NOTICES.md` for source attribution.
