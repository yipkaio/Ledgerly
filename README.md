<p align="center">
  <img src="docs/assets/screenshots/153316.png" alt="Ledgerly logo" width="120">
</p>

<h1 align="center">Ledgerly</h1>

<p align="center">
  AI-assisted receipt classification, human review and bank reconciliation for bookkeepers.
</p>

## Documentation map

- [Documentation guide](docs/index.md) — organised entry point for operators,
  reviewers and developers.
- [Illustrated user guide](docs/user-guide.md) — privacy-reviewed walkthrough of
  receipt review, reporting and monthly close.
- [Architecture and data flow](docs/architecture.md) — numbered receipt workflow
  and the deployed AWS Lightsail topology.
- [Security model](docs/security.md) — trust boundaries, secrets, release checks
  and accepted MVP limitations.
- [Demo-readiness checklist](docs/demo-readiness.md) — final release gate and
  end-to-end acceptance flow.

The application is a single trusted workspace. AI components extract, recommend
and explain; deterministic controls and human reviewers retain authority over
financial records.

Receipt details now support **Undo deletion**, audited **Reprocess receipt** extraction drafts, and a live totals reconciliation panel. See [reprocessing and reconciliation](docs/reprocessing.md) for workflow, eligibility, costs and schema v5 migration notes.

Monthly close now accepts bank-issued **PDF statements** through a signed preview-and-confirm flow, including request-only passwords for encrypted PDFs, private deterministic parsing, explicit opt-in AI fallback, balance checks, and retained source provenance. Normalized CSV remains available as a fallback.

## Three-agent AI architecture

The working application now organises AI responsibilities into three bounded
logical agents:

1. **Document Intelligence** extracts structured receipt data and, only with
   explicit consent, can fall back to AI for bank-statement layouts that the
   private deterministic parser cannot read.
2. **Classification and Compliance** performs expense categorisation, exact
   vendor normalisation, deterministic evidence/control checks and optional
   guidance for the human Review Queue.
3. **Finance Copilot** explains deterministic reconciliation exceptions,
   prepares monthly-close briefs and answers read-only questions scoped to one
   month and currency.

These are service boundaries, not autonomous accounting users. Arithmetic,
duplicates, vendor lookup, confidence gating, reconciliation matching, payment
state and approvals remain deterministic or human-controlled. The agents cannot
approve/reject expenses, change payment status, post entries, initiate payments,
override matches or declare fraud.

New authenticated, on-demand endpoints are available under `/ai`:

- `GET /ai/agents`
- `POST /ai/receipts/{receipt_id}/review-assistance`
- `POST /ai/reconciliation/explain`
- `POST /ai/monthly-close/brief`
- `POST /ai/copilot/ask`

Advisory calls use task-specific Pydantic schemas, bounded/minimised inputs,
prompt-injection instructions, safe failures, 15-minute in-process caching and
audit metadata with a prompt version and SHA-256 input fingerprint. Finance
Copilot answers are deliberately concise: direct answers come first, exception
lists are bounded, and advisory generation is limited to 500 output tokens.

Questions outside receipt, bank-transaction, reconciliation and monthly-close
context are refused before any model call. Requests for secrets, hidden prompts
or system instructions are also refused. If the model returns malformed output
for an exception explanation or close brief, the API returns a clearly labelled
deterministic fallback based only on recorded reconciliation totals and statuses;
it does not invent an AI interpretation. See [AI agent architecture](docs/ai-agents.md)
for endpoint examples, authority boundaries, privacy controls and the human workflow.

## Docker backend

Docker packaging is available for the existing backend, including both OCR
engines, persistent SQLite/upload/cache volumes, a non-root runtime and private
localhost access. See [Docker setup and testing](docs/docker.md) for Windows,
container smoke tests, backups and the Lightsail deployment. The Docker image
includes the built review UI at `/ui/`. No AWS resources are provisioned by these files.

## Authentication and production deployment

Local development continues to use the shared app key. Production can use Firebase
email/password for one pre-created bookkeeper UID; there is no self-service
registration or multi-role permission system. `hybrid` mode retains the app key
only for controlled integrations such as the deployed Telegram/OpenClaw relay.
The browser refreshes Firebase ID tokens in memory, and the backend verifies the
account with Firebase before accepting protected requests.

A production Compose overlay adds Caddy HTTPS, disables API documentation and keeps
the FastAPI service private behind the reverse proxy. See
[authentication and production deployment](docs/authentication.md) and the
[demo-readiness checklist](docs/demo-readiness.md).

## Current status

The application now provides a secure FastAPI receipt-processing pipeline:

- `GET /health` for service health checks.
- `POST /receipts/upload` for authenticated JPEG/PNG and bounded PDF uploads.
- A 5 MB default size limit, file-signature checks, generated storage names, and cleanup of rejected uploads.
- SHA-256 exact-duplicate blocking before OCR/LLM work, plus strict post-extraction duplicate warnings.
- PaddleOCR text detection and recognition, including orientation correction, image unwarping, and recognition confidence.
- Configurable Tesseract fallback with a bounded subprocess timeout.
- Structured receipt extraction through the organiser's text-only LLM gateway.
- Strict receipt and line-item schemas, optional explicit discounts, and deterministic amount reconciliation checks.
- Exact vendor-to-category lookup before AI classification.
- A fixed-category expense classifier for unmatched vendors, with optional business purpose and a configurable confidence gate.
- Three bounded AI-agent service layers for document intelligence, classification/control review, and read-only finance assistance.
- Automated tests that mock both OCR providers and both gateway agents, so tests do not download models, require OCR installation, make network calls, or consume API credits.

SQLite persistence, authenticated receipt history, human approval/rejection, and append-only amendments are implemented. The React + TypeScript workspace supports uploads, paginated history, pending reviews, protected originals, verified corrections, confirmation dialogs, explicit amendment mode, structured receipt summaries, and field-level audit viewing. Follow the [frontend setup and review guide](docs/frontend.md). See [Human review API](docs/reviews.md) for manual payloads, validation, and migration precautions. Firebase email/password authentication is available for a single pre-approved
bookkeeper account, with a hybrid mode that preserves the app key for trusted
service integrations. Telegram/OpenClaw receipt intake is implemented as a secure, owner-only relay; follow the [deployment and test guide](docs/telegram-openclaw.md).

## SQLite persistence and receipt history

The workspace starts with **Main dashboard**, followed by **Monthly close**, **Upload receipt**,
**Pending reviews**, **Receipt history**, and **Deleted receipts**. The dashboard opens on
**All time**, from the first dated accepted receipt through the latest. A saved **default
reporting currency** converts supported currencies into one management view; native-currency
views remain available. Beside it, choose the latest month, latest three months, latest receipt year,
or an inclusive custom date range. The same receipt-date range drives the accepted expense
total, accepted count, category breakdown and trend. The chart shows monthly points for
up to 24 months and yearly points for longer ranges, with keyboard/touch inspection and an
exact-values table. Receipts without a date are available in history but excluded from dated
dashboard reporting. **View this date range** opens history already filtered to the same dates
and the approved, amended and auto-filed statuses. History supports checkbox-based
multi-selection for categories, statuses, and currencies, with animated authenticated
previews beside each receipt. See the
[workflow roadmap](docs/workflow-roadmap.md) for duplicate/amendment behavior,
filtered Excel export, PDF ingestion, and remaining usability priorities.

For manual review, follow the numbered Swagger endpoints and the
[review walkthrough and troubleshooting table](docs/reviews.md). Review templates
must be edited before submission. Approvals reject obvious placeholders, missing
essential fields and currencies outside the documented MVP subset. Approved
records can be corrected with append-only amendments; rejected records cannot be reopened.

Set `DATABASE_PATH=data/expenses.db` in `.env` (the default). Python's built-in
SQLite driver is used; no database server or new dependency is required. On first
database use, schema version 8 and the three initial vendor mappings are created
transactionally. Existing mappings are not overwritten on restart. The runtime
lookup reads `vendor_category_mappings`; the dictionary in `app/classification.py`
is now the initial seed and legacy lookup helper, not the upload lookup source.

Existing version 1–7 databases migrate transactionally on first use. Back up the
database and uploads before upgrading; the previous application cannot read
schema version 8. Human decisions, amendments, lifecycle events, reprocessing attempts,
and payment follow-up live in append-only audit tables,
separately from the original AI evidence.

Core tables include `receipts` (metadata, OCR, extraction JSON and timestamps), `line_items`
(ordered item JSON), `classifications`, review/lifecycle audit tables, `bank_statements`,
`bank_transactions`, and `receipt_payment_events`. JSON preserves the existing validated response fields.
Foreign keys are enabled on every connection. Final extraction, line items and
classification are committed together. No transaction stays open during OCR or
gateway calls. Database operations run outside the async event loop.

All history endpoints require the configured application authentication. Local
and trusted-integration requests use `X-API-Key`; the production browser uses an
allowed Firebase bearer token in `hybrid` mode:

- `GET /receipts/{receipt_id}` returns saved evidence, extraction, classification,
  safe error information and `processing_status`. Unknown IDs return 404.
- `GET /receipts?limit=20&offset=0` returns newest-first metadata, a total count,
  and pagination. Maximum page size is 100; OCR text is excluded from list results.
- `GET /receipts?decision=REVIEW_QUEUE` filters saved review decisions.
- `GET /receipts?query=...&category=...&currency=...&state=...&date_from=...&date_to=...`
  filters the latest effective values while preserving pagination. Repeat `category`,
  `currency`, or `state` to match any selected value in that filter group.
- `POST /receipts/export` downloads selected IDs or all filtered results as a
  bounded three-sheet `.xlsx` workbook.
- `GET /reviews` returns the outstanding human-review queue, excluding finalized reviews.
- `POST /receipts/{receipt_id}/review` approves or rejects a queued receipt.
- `GET /receipts/{receipt_id}/reviews` returns its review audit history.
- `POST /receipts/{receipt_id}/amendments` creates a new effective accepted version.
- `GET /receipts/{receipt_id}/amendments` returns immutable amendment history.
- `GET /dashboard` returns authenticated counts and accepted totals by currency;
  inclusive `date_from`/`date_to` or `dated_only=true` filters dated accepted totals.
- `GET /receipts?processing_status=FAILED` finds failed processing attempts.

`processing_status` is `PROCESSING`, `COMPLETED`, `REVIEW_QUEUE`, or `FAILED`.
The existing upload response remains `status: processing_complete` for backwards
compatibility. `AUTO_FILED` is an internal decision, not submission to an external
accounting system. `REVIEW_QUEUE` does not mean a human has approved the expense.
These original processing fields remain historical after review. Receipt detail
includes review, amendment, effective-value and version fields; use `/reviews` for pending work.

In the UI, apply history filters before selecting rows. Category, status, and currency
filters accept multiple checkbox selections. Selection is retained while you paginate
and is cleared when filters change. **Export selected** sends only the explicit IDs;
**Export filtered** exports the server-side result, up to 1,000 receipts. Uploads use
guided business-purpose choices; selecting **Other** reveals a required custom-purpose
field. See [History filters and Excel export](docs/export.md).

PDF ingestion prefers embedded text and OCRs only pages that need it. Parsing and
rendering run within explicit page, time, dimension and pixel limits; a protected
first-page preview is generated for the UI. See [PDF receipt ingestion](docs/pdf.md).

After a validated image is saved, a processing record is created before OCR runs.
OCR evidence is saved before extraction. Controlled processing failures return the
existing safe error body plus `X-Receipt-ID` so the failure can be retrieved.
OCR-failed images are still removed; extraction-failed images are retained.
Validation failures and dependency initialization failures before the handler runs
do not create records. A failed database write never returns processing success.
If the database remains unavailable, or the process is killed, a record may remain
`PROCESSING`; it is not automatically retried or marked failed on restart.

### Verify and inspect

Upload through `/docs`, copy `receipt_id`, restart Uvicorn, then call the new
GET endpoint with that ID and your app key. The saved result should still exist.
You can open `data/expenses.db` with a SQLite database viewer to inspect tables.
Automated tests use isolated temporary databases and mock all OCR/gateway calls.

### Security and backup limits

This remains a single trusted workspace. In production, only the configured
Firebase UID should use the web UI; the shared app key is reserved for trusted
integrations in hybrid mode. Keep Uvicorn private behind the HTTPS reverse proxy. No public file-download, deletion, or mapping-write API is added.
Internal filesystem paths and raw exception messages are excluded from history.
The database and uploaded images contain sensitive data: restrict filesystem
access and never commit them. SQLite files and sidecars are ignored by Git.

For a consistent MVP backup, use SQLite's online backup API, copy the retained
uploads, verify database integrity and checksum the resulting archive. Copy the
archive to a protected off-instance destination; a Lightsail snapshot is an
additional recommended layer. Restore the database and evidence together. Follow
the [Docker backup procedure](docs/docker.md#production-backup).
There is a five-second lock timeout;
heavy concurrent writes can return 503. Existing uploads made before this commit
are not automatically imported, and stalled-processing retry jobs remain future
work. Exact and probable duplicate checks are implemented. Tests against SQLite
do not claim PostgreSQL compatibility.

## Confirmed pipeline

The hackathon gateway accepts text prompts but did not receive images during testing. Receipt images must therefore be processed locally before the LLM call:

1. Receive and validate a receipt image.
2. Run local PaddleOCR, or Tesseract when selected as the fallback.
3. Send OCR text to the text-only LLM gateway and validate the returned receipt JSON.
4. Apply a deterministic vendor mapping when one is safe.
5. Classify unmatched or mixed-purpose expenses with the LLM.
6. Auto-file results at or above the confidence threshold; otherwise send them to review.

Business purpose should be optional input. Missing context must lower confidence for ambiguous receipts instead of forcing a guess. The initial confidence threshold is `0.80`.

## Local setup (Windows PowerShell)

Requirements: Python 3.11. PaddleOCR is the default provider; [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) is an optional fallback.

```powershell
git clone https://github.com/yipkaio/expense-classification-agent.git
cd expense-classification-agent
py -3.11 -m venv .venv311
$python = ".\.venv311\Scripts\python.exe"
& $python -m pip install --upgrade pip setuptools wheel
& $python -m pip install -e ".[test,ocr-paddle]"
Copy-Item .env.example .env
```

Store local secrets in the ignored `.env` file created above. Generate `APP_API_KEY` once, paste it into `.env`, add the organiser-provided `LLM_GATEWAY_API_KEY`, and never commit either value:

```powershell
[guid]::NewGuid().ToString("N") | Set-Clipboard
notepad .env

& $python -m uvicorn app.main:app --reload --env-file .env
```

Open `http://127.0.0.1:8000/docs`, paste the saved `APP_API_KEY` value into the `X-API-Key` request header, and submit a JPEG, PNG, or PDF receipt. PDFs default to at most three pages; encrypted and malformed files are rejected. Usable embedded PDF text avoids OCR, while scanned pages use the configured OCR engine. `business_purpose` is optional. A successful response has status `processing_complete` and includes OCR/text evidence, validated `extracted_data`, and a confidence-gated `classification`. Each successful upload makes one extraction call; only unmatched vendors make an additional classification call. PaddleOCR downloads its model files on the first real OCR request and caches one pipeline instance per application process.

To use the existing Tesseract fallback instead, change `OCR_ENGINE=tesseract` in `.env` and restart Uvicorn. Tesseract does not expose a recognition confidence through this integration, so `ocr_confidence` will be `null`.

## OCR engine comparison

Both OCR engines were tested locally on the same 263,222-byte JPEG receipt using a Windows CPU environment.

| Engine | Processing time | Reported confidence | Observed result |
|---|---:|---:|---|
| Tesseract | 2–3 seconds | Not available | Faster, but it missed the vendor name and misread parts of the address, fax number, GST number, and receipt table. |
| PaddleOCR | About 10 seconds | 0.994 | It detected the vendor and produced substantially clearer identity, contact, tax, receipt, total, and line-item text. |

PaddleOCR is the default because accurate vendor and amount recognition is more important than raw OCR speed for downstream vendor lookup and structured expense extraction. Tesseract remains available as a faster, lightweight alternative and fallback.

Choose an engine in `.env` before starting Uvicorn:

```dotenv
OCR_ENGINE=paddle       # Accuracy-focused default
# or
OCR_ENGINE=tesseract    # Faster alternative
```

These results are an indicative comparison from one receipt, not a comprehensive benchmark or a claim that PaddleOCR is always more accurate. PaddleOCR's value is its average recognition confidence across accepted text lines; it is not an accounting-field accuracy score and cannot be compared directly with the current Tesseract response, which does not include confidence.

Run the tests with:

```powershell
& $python -m pytest
```

### PaddleOCR Windows CPU compatibility

The project pins PaddlePaddle `3.2.2` because PaddlePaddle `3.3.x` has a CPU/oneDNN regression that can raise `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` during PP-OCR inference. If `3.3.x` was previously installed in `.venv311`, stop Uvicorn and restore the pinned dependency with:

```powershell
$python = ".\.venv311\Scripts\python.exe"
& $python -m pip install --force-reinstall "paddlepaddle==3.2.2"
& $python -m pip install -e ".[test,ocr-paddle]"
```

## Gateway configuration

The confirmed endpoint is `POST https://api.softwaresystems.app/api/chat` using the `X-API-Key` header and model `global.anthropic.claude-sonnet-4-5-20250929-v1:0`. Keep these values in environment variables; never commit the real API key.

The extraction client sends only OCR text, requests deterministic JSON with an 800-token default output allowance, and validates every response against strict Pydantic models. Receipt-level `discount_amount` records an explicitly printed discount applied after subtotal and before tax; it is separate from optional line-item `discount_percent` and `discount_amount` values. All discount fields remain `null` unless printed on the receipt. If OCR column order causes `unit_price` and `discount_percent` to be reversed, the application swaps them only when the original calculation fails and the swapped calculation uniquely reconciles within the two-cent tolerance. Every such correction sets `needs_review` and records an audit reason. Optional JSON Markdown fences are accepted, while empty, truncated, malformed, or schema-invalid responses are rejected. Required-field, discount, and arithmetic inconsistencies set `needs_review` without silently changing the extracted amounts.

Gateway errors use controlled API responses: `502` for invalid model output, `503` when the service is unavailable, and `504` for timeouts. The uploaded receipt image is retained when LLM extraction fails so it can be recovered once persistence and the review queue are implemented. Automated tests use a mocked HTTP transport and never call the live gateway.

## Expense classification

The backend first checks a small set of manually validated, exact vendor mappings. Vendor names are normalized for case and punctuation, but substring matches are prohibited so broad retailers such as MR D.I.Y. are not mapped accidentally. Unmatched vendors are sent to the classification agent with the extracted receipt and optional business purpose.

The agent must select one fixed category and return a confidence score from zero to one. `CLASSIFICATION_CONFIDENCE_THRESHOLD` defaults to `0.80`. Extraction-review flags, classifier-review flags, or confidence below the threshold produce `REVIEW_QUEUE`; only a clean result at or above the threshold produces `AUTO_FILED`. Invalid or unavailable classification responses also produce a safe review decision rather than losing the accepted receipt.
# Receipt retention and voiding

The workspace now includes **Deleted receipts** (restore within 30 days) and audited **Void receipt** for approved/auto-filed records. Deletion and voiding exclude records from dashboards and normal exports. Schema v4 migrates existing records without deleting them. Back up the database and uploads before deployment. See [receipt lifecycle](docs/receipt-lifecycle.md) for eligibility, cleanup timing, duplicate handling, and verification.

# Monthly reconciliation

The **Monthly close** workspace opens with an all-years overview of accepted-receipt and statement months, including months with no imported bank statement. The detail view shows evidence and exceptions, and lets reviewers record an audited monthly review that becomes outdated if evidence changes. It imports bank-issued PDFs through a signed preview-and-confirm flow, with normalized CSV as a fallback. The PDF preview now explains the balance calculation and blocks a mismatch. Neighboring-month possible matches remain inspection hints; they do not automatically mark receipts paid. **View source** shows a bounded first-page image for PDFs and text for CSVs; **Download** retrieves the retained original. Receipt-history Excel summaries count accepted spend only, by original currency. Monthly Close exports distinguish suggested matches from recorded payment events and link every debit to its statement source; duplicate bank debits stay unmatched until reviewed. PDF passwords are request-only and the AI fallback requires explicit consent. Schema v9 preserves prior data and adds monthly review events. See [monthly reconciliation](docs/monthly-reconciliation.md) for the PDF/CSV contract, matching rules and Singapore record-control boundaries.

The dashboard saves a default reporting currency and consolidates supported currencies using a
dated, cached ECB reference-rate snapshot. The rate date and cached-rate status remain visible;
converted totals are management estimates and never overwrite original receipt amounts. If
conversion is unavailable, the UI offers native-currency views rather than a partial total.

Monthly close lets users **Remove** a wrongly imported statement, with a name, reason and
confirmation. This is reversible exclusion, not permanent erasure: the retained source and
debits remain available under **Removed statements → Restore**. Matches and totals recalculate,
while receipts and manual payment notes remain unchanged. Removal/restoration events are
appended to the statement metadata in a transaction; no database migration is required.
The authenticated endpoint is `POST /bank-statements/{statement_id}/lifecycle` with
`action` (`REMOVE` or `RESTORE`), `actor`, and `reason`.
Re-uploading an identical removed file remains blocked; restore the existing import instead.
Bank-source and attention-only filters simplify review; summary totals and exports continue
to cover the entire selected month. Removed statements are excluded from active Excel exports.

Opening a receipt from Monthly Close now returns to its selected month, currency, and filters.
Human payment-status changes retain an append-only history visible in both Monthly Close and
receipt detail. Trade payable follow-up may include separate invoice due and planned payment
dates; neither schedules a transfer nor marks the receipt paid. Spending review prompts are
deterministic. The animated receipt assistant opens Finance Copilot in a read-only side panel
with period-scoped questions, brief and exception actions; its motion respects reduced-motion
settings. See [monthly reconciliation](docs/monthly-reconciliation.md) for the workflow.
