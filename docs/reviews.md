# Human review (private MVP)

All three routes require `X-API-Key`: `GET /reviews?limit=20&offset=0`,
`POST /receipts/{receipt_id}/review`, and `GET /receipts/{receipt_id}/reviews`.
No OCR or LLM calls are made by review actions. Use the SSH tunnel and `/docs`.

1. List `/reviews`, then retrieve a queued receipt with `GET /receipts/{id}`.
2. Compare the original image with OCR and extracted fields. Image viewing through
   the API is not included in this commit; use the original image you uploaded.
3. Submit a new UUID `request_id`, `expected_version: 0`, `decision: APPROVED`,
   a nonblank `reviewer` and `note`, and `evidence_confirmed: true`.
   Include the entire corrected extraction as `corrected_data` (copy the returned
   extraction and edit it) and one allowed `category`, e.g. `Office Supplies`.
   Unknown fields are rejected. Discount fields remain nullable.
4. Arithmetic checks rerun without automatic price/discount swapping. Historical
   AI reasons are preserved in original evidence, not reused as current validation
   failures. Any remaining deterministic issue requires `override_reason` of at
   least 10 characters. Overrides preserve the issues; they do not hide them.
5. For rejection use `decision: REJECTED`, with a note and evidence confirmation,
   but omit corrected_data, category and override_reason.
6. Re-fetch the receipt and its review history. The top-level extraction,
   classification and processing_status remain ORIGINAL AI evidence. The new
   `review.decision`, `review.final_data`, and `review.category` are authoritative
   after human review. `review_version` becomes 1. The old `/receipts` filters
   deliberately describe original processing; use `/reviews` for the active queue.

Exact retries with the same request ID and payload return the original result.
Reusing an ID for different content, stale versions, reviewing nonqueued receipts,
or a second final decision returns 409. No reopening/edit-after-finalization is
supported yet. Pending queue pages exclude both approved and rejected receipts.
The decision and before/after audit event commit atomically. SQLite serializes
concurrent approvals. Audit UPDATE/DELETE triggers protect against accidental
edits, not a server administrator deliberately modifying the database.

Reviewer identity is explicitly `self_reported`: a shared app key cannot prove
who reviewed a receipt. All key holders share read/write access to this workspace.
Do not expose this as a public multi-user service until verified authentication
and reviewer authorization are implemented. Review never modifies vendor rules.

## Migration, verification and deployment

Schema version 1 upgrades transactionally to version 2 on first database access
(including container startup). Two new tables and audit protection triggers are
added; original receipt, classification and vendor rows are not rewritten.
There is no schema downgrade. The old image rejects schema 2.

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
