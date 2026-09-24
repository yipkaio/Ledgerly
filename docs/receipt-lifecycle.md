# Receipt lifecycle

The [user guide](user-guide.md#deleted-receipts-and-restoration) shows where to
find the restore deadline and lifecycle history. Deletion removes eligible
records from ordinary totals during a bounded recovery window; accepted
records use a separate audited void action.

The authenticated workspace supports **Move to deleted receipts**, **Restore receipt**, and **Void receipt**. In production the approved Firebase account signs in to the browser and a separate app key serves trusted integrations. Names typed into lifecycle events are self-reported audit labels, not verified personal identities or roles.

## Rules

| Record | Action |
| --- | --- |
| Pending, failed, rejected | Move to deleted receipts; reason required |
| Processing | Wait for processing to complete |
| Approved, auto-filed, amended | Void only; reason required; original evidence retained |
| Deleted, before deadline | Restore if no identical retained file exists |
| Deleted, after deadline | No restore; automatic permanent erasure |
| Voided | Read-only history; no delete, restore, rejection, or amendment |

Deletion hides records from ordinary history, review queues, dashboard counts/totals and exports. Deleted receipts appear only in their dedicated UI tab or an explicit `state=DELETED` list query. Voided receipts remain searchable in history but are excluded from dashboards and exports (including explicit ID exports). Previously downloaded spreadsheets do not change.

Identical file uploads may be repeated after soft deletion. Restoration is blocked when the hash matches any non-deleted record, including a voided one. Voiding does not release the file hash. Potential-duplicate searches exclude deleted and voided records.

## Retention and operations

The restore deadline is exactly 30 days after deletion, in UTC; the UI displays it in the browser's timezone. The application checks expiry at startup and hourly while running, purging up to 100 expired receipts per pass. Erasure therefore occurs on the next successful cleanup pass, not exactly at the deadline. If the server is offline, erasure resumes at startup. Failed file removals retain the database record for retry.

Cleanup removes only server-generated UUID filenames within the configured upload directory, never stored arbitrary paths. It removes the receipt's dependent rows, including rejection/lifecycle evidence, only after expiry. Approved and amendment audit protections remain. Voided receipts have no purge deadline. A generic server warning indicates a failed cleanup pass without logging receipt contents.

This is application retention, not deletion from independent backups. Backups retain their own lifetime. Before deploying, back up the database and uploads together. Migration from schema versions 1–3 to 4 preserves existing evidence and marks every current record ACTIVE. No existing record is automatically deleted or voided on migration.

`POST /receipts/{id}/lifecycle` accepts `request_id`, `action`, `expected_version` (lifecycle_version), `expected_record_version`, `reviewer`, and `reason`. Reasons require 10–2000 characters. Use the same UUID and payload after an uncertain response. Actions run inside a write transaction; stale versions, processing receipts, invalid transitions, and restore collisions return 409. Inspect the current record before retrying a conflict.

## Validation

Run `python -m pytest`, then from frontend run `npm ci`, `npm run lint`, `npm run build`, and `npm test`. Lifecycle tests use synthetic files and mocked browser APIs; they never call the LLM or operate on production receipts. Check desktop and mobile dialogs, keyboard focus, Deleted receipts, restore deadlines, and voided read-only history before deployment.
