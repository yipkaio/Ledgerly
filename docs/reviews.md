# Human review (private MVP)

All review and amendment routes require `X-API-Key`: `GET /reviews?limit=20&offset=0`,
`POST /receipts/{receipt_id}/review`, `GET /receipts/{receipt_id}/reviews`, and
`POST`/`GET /receipts/{receipt_id}/amendments`.
No OCR or LLM calls are made by review actions. Use the SSH tunnel and `/docs`,
or follow the [receipt workspace guide](frontend.md) to review in `/ui/`.

## Start here in Swagger

Local: http://127.0.0.1:8000/docs. AWS tunnel: http://127.0.0.1:18000/docs.
These are separate databases. Keep your tunnel open for AWS. Use the APP_API_KEY
configured on the server you selected, never the LLM gateway key. Do not share
Swagger's Curl block: it includes your key. Share redacted Server response details.

| Step | Endpoint | What to do |
|---|---|---|
| 1 | GET `/reviews` | Try it out, enter key, Execute. Copy a pending receipt_id. |
| 2 | GET `/receipts/{receipt_id}` | Enter ID and key, Execute. This is read only, with no JSON body. |
| 3 | POST `/receipts/{receipt_id}/review` | Writes a final decision. Follow the approval/rejection instructions below. |
| 4 | GET `/receipts/{receipt_id}/reviews` | Inspect the saved audit event. |

In step 2, `review: null` and `review_version: 0` mean no review has been saved.
Copy ONLY the `extracted_data` object from **Server response → Response body**.
The generated Curl is the request, not proof it succeeded.

Generate a new request ID in Windows PowerShell:

```powershell
[guid]::NewGuid().ToString()
```

`receipt_id` selects the receipt; `request_id` identifies this submission. Neither
is an API key. The `/ui/` workspace generates request IDs automatically and
retains an identical payload for retry after an uncertain response.

In POST, select the **approve** or **reject** example from the Examples dropdown.
The templates intentionally fail validation until edited: replace every REPLACE_
value, set evidence confirmation after inspection, and for approval replace the
null corrected_data with the complete extraction copied in step 2. Never submit
the generic schema sample with `string`, arbitrary currency or zero amounts.

## Decide using evidence

Check vendor, receipt/date, currency, all items (including missing/duplicate rows),
discount columns, tax, rounding and the final payable total against the image.
Do not confuse cash tendered with the total. Read BOTH sets of AI review reasons.
High OCR confidence and reconciling arithmetic do not prove correct extraction.
For mixed purchases, establish actual business purpose before choosing a category;
the API permits one category only and does not split expenses. Record the purpose,
category rationale and corrections in the note. Do not invent a business purpose
for a real receipt. For a mock test, explicitly label the assumed purpose as mock.
If you need more evidence, leave it pending; rejection is a final decision, not a
request for more information. The review API does not edit business_purpose itself.

Optional absent fields and unprinted discounts stay null; zero is a real amount,
not a substitute for unknown. Zero-total receipts are allowed if actually verified.
Approval requires nonmissing vendor, date, currency and total_amount. Supported
review currencies are **SGD, MYR, USD, EUR, GBP, AUD** (a deliberate MVP subset,
not a full currency registry). Do not relabel an unsupported currency to pass.
These rules apply to human reviews; original LLM extraction is preserved as-is.
Blank/example strings are rejected, but this is an accidental-input guard, not
proof that a reviewer supplied truthful information.

## Submit and verify

1. List `/reviews`, then retrieve a queued receipt with `GET /receipts/{id}`.
2. Compare the original image with OCR and extracted fields. Use the authenticated
   GET `/receipts/{id}/image` endpoint or the file viewer in `/ui/`. Missing retained
   files return 404; do not approve without checking the original evidence.
3. Submit a new UUID `request_id`, `expected_version: 0`, `decision: APPROVED`,
   a nonblank `reviewer` and `note`, and `evidence_confirmed: true`.
   Include the entire corrected extraction as `corrected_data` (copy the returned
   extraction and edit it) and one allowed `category`, e.g. `Office Supplies`.
   Unknown fields are rejected. Discount fields remain nullable.
4. Arithmetic checks rerun without automatic price/discount swapping. Historical
   AI reasons are preserved in original evidence, not reused as current validation
   failures. Any remaining deterministic issue requires `override_reason` of at
   least 10 characters. Overrides preserve the issues; they do not hide them.
   They cannot bypass missing essential fields, unsupported currency, placeholders
   or schema errors. Fix mistakes first. Arithmetic uses a 0.02 tolerance and may
   not model service charges, invoice-wide discounts or every tax layout; record
   a specific evidence-based explanation only when accepting a known discrepancy.
5. For rejection use `decision: REJECTED`, with a note and evidence confirmation,
   but omit corrected_data, category and override_reason.
6. Re-fetch the receipt and its review history. The top-level extraction,
   classification and processing_status remain ORIGINAL AI evidence. The new
   `review.decision`, `review.final_data`, and `review.category` are authoritative
   after human review. `review_version` becomes 1. The old `/receipts` filters
   deliberately describe original processing; use `/reviews` for the active queue.

Exact retries with the same request ID and payload return the original result.
Reusing an ID for different content, stale versions, reviewing nonqueued receipts,
or a second final decision returns 409. Auto-filed and approved receipts can be
amended using current `record_version`; rejected receipts cannot be reopened.
Pending queue pages exclude both approved and rejected receipts.
The decision and before/after audit event commit atomically. SQLite serializes
concurrent approvals. Audit UPDATE/DELETE triggers protect against accidental
edits, not a server administrator deliberately modifying the database.

## Troubleshooting and test checklist

| Symptom | Next action |
|---|---|
| Empty queue | Check server/port; AUTO_FILED, failed, processing and finalized receipts are excluded. Refresh from offset 0 after reviews change the queue. |
| 401 | Use the selected server's APP_API_KEY. |
| 404 | Check ID and server; local and AWS receipts differ. |
| 409 | GET detail. Another reviewer may have finalized it, or request_id was reused with different data. New IDs cannot reopen decisions. |
| 422 | Read detail/field location; replace templates and fix missing, unsupported or inconsistent values. Do not add a meaningless override. |
| 503 or lost connection | Check health/configuration; GET detail/history before retrying the same request. Do not re-upload just to retry a review. |
| Original status still REVIEW_QUEUE | Expected: original AI evidence stays unchanged. Read review.decision and the pending /reviews endpoint. |
| Already approved with wrong data | GET receipt detail, copy `record_version` and effective data, then use the UI's **Save amendment** action or POST `/receipts/{id}/amendments`. Never edit audit rows directly. |

Use TWO disposable queued records: approve one with verified data and reject the
other with a clear reason. Confirm 200, review_version 1, removal from /reviews,
and exactly one audit event each. Repeat an identical valid submission: expect the
same result and no extra event. A different decision on that finalized receipt
must return 409. Restart the backend and confirm decisions remain. Bad input must
return 422 with no review/audit saved and the receipt still pending.
Uploading a new test image may consume gateway credits; reviewing existing records
does not. Model routing can vary, so an ambiguous image is not guaranteed to queue.

This update migrates the database to schema version 3 without rewriting existing
approvals. Previously accepted invalid requests remain visible in review history;
use an audited amendment to correct an approved record. Keep invalid test records out of reports.

Reviewer identity is explicitly `self_reported`: a shared app key cannot prove
who reviewed a receipt. All key holders share read/write access to this workspace.
Do not expose this as a public multi-user service until verified authentication
and reviewer authorization are implemented. Review never modifies vendor rules.

## Migration, verification and deployment

Schema versions 1 and 2 upgrade transactionally to version 3 on first database
access (including container startup). Duplicate metadata, amendment tables and
audit protection triggers are added; original receipt, classification and vendor
rows are not rewritten. There is no schema downgrade. Older images reject schema 3.

Run the full local test suite and Docker tests BEFORE updating AWS:

```powershell
python -m pytest -q
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
```

The authoring workspace cannot run Docker; the two native container tests must
be verified separately. Test the review of a disposable receipt locally first.

On AWS, schedule a short maintenance window. Stop the API, preserve its old image
under a unique tag, and copy the entire `/app/data` from the stopped container
into a NEW protected backup directory. Follow [Docker backup guidance](docker.md).
Keep an off-instance backup and confirm it contains the database and uploads.
Only then pull the commit, build the image, and start it with the existing volumes.
Never use `down -v`. Confirm health, old receipt retrieval, queue listing and one
review through the private tunnel. No new credentials are needed.

Rollback requires BOTH the old image and the pre-migration data backup, restored
with all writers stopped. Preserve post-upgrade data separately first: restoring
the old backup loses any receipts/reviews created after it. Do not simply retag
the old image against the upgraded database. Ask for a reviewed restore procedure
before replacing production data.
