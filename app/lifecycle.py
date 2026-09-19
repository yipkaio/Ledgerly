"""Recoverable deletion and append-only voiding for the trusted workspace."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.history import HISTORY_CTE
from app.review import ReviewConflict, ReviewNotFound, reject_placeholder


class LifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    action: Literal["DELETE", "RESTORE", "VOID"]
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    expected_record_version: Annotated[int, Field(strict=True, ge=0)]
    reviewer: Annotated[str, Field(min_length=1, max_length=100)]
    reason: Annotated[str, Field(min_length=10, max_length=2000)]

    @field_validator("reviewer", "reason")
    @classmethod
    def valid_text(cls, value):
        reject_placeholder(value)
        return value


LIFECYCLE_SCHEMA = (
    "ALTER TABLE receipts ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(lifecycle_state IN ('ACTIVE','DELETED','VOIDED'))",
    "ALTER TABLE receipts ADD COLUMN lifecycle_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE receipts ADD COLUMN deleted_at TEXT",
    "ALTER TABLE receipts ADD COLUMN purge_after TEXT",
    "DROP INDEX exact_receipt_content",
    "CREATE UNIQUE INDEX exact_receipt_content ON receipts(content_sha256) WHERE content_sha256 IS NOT NULL AND lifecycle_state<>'DELETED'",
    "CREATE INDEX receipt_purge ON receipts(lifecycle_state, purge_after)",
    "CREATE TABLE lifecycle_events (receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id), version INTEGER NOT NULL, request_id TEXT UNIQUE NOT NULL, request_json TEXT NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY(receipt_id, version))",
    "CREATE TRIGGER lifecycle_no_update BEFORE UPDATE ON lifecycle_events BEGIN SELECT RAISE(ABORT, 'Immutable audit'); END",
    "CREATE TRIGGER lifecycle_no_delete BEFORE DELETE ON lifecycle_events WHEN NOT EXISTS (SELECT 1 FROM receipts WHERE receipt_id=OLD.receipt_id AND lifecycle_state='DELETED' AND julianday(purge_after)<=julianday('now')) BEGIN SELECT RAISE(ABORT, 'Immutable audit'); END",
    "DROP TRIGGER review_audit_no_delete",
    "CREATE TRIGGER review_audit_no_delete BEFORE DELETE ON review_audit WHEN NOT EXISTS (SELECT 1 FROM receipts r JOIN receipt_reviews v USING(receipt_id) WHERE r.receipt_id=OLD.receipt_id AND r.lifecycle_state='DELETED' AND julianday(r.purge_after)<=julianday('now') AND json_extract(v.result_json,'$.decision')='REJECTED') BEGIN SELECT RAISE(ABORT, 'Immutable audit'); END",
)


def apply_lifecycle(store, receipt_id: str, request: LifecycleRequest) -> dict:
    payload = json.dumps(request.model_dump(mode="json"), sort_keys=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        timestamp = datetime.now(timezone.utc)
        prior = db.execute("SELECT * FROM lifecycle_events WHERE request_id=?", (str(request.request_id),)).fetchone()
        if prior:
            if prior['receipt_id'] == receipt_id and prior['request_json'] == payload:
                return json.loads(prior['event_json'])
            raise ReviewConflict("Request ID was already used with different content")
        row = db.execute("SELECT * FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
        if row is None:
            raise ReviewNotFound("Receipt not found")
        if row['processing_status'] == 'PROCESSING':
            raise ReviewConflict("Wait for receipt processing to finish")
        version = db.execute("SELECT count(*) FROM receipt_reviews WHERE receipt_id=?", (receipt_id,)).fetchone()[0] + db.execute("SELECT count(*) FROM receipt_amendments WHERE receipt_id=?", (receipt_id,)).fetchone()[0]
        if row['lifecycle_version'] != request.expected_version or version != request.expected_record_version:
            raise ReviewConflict("Receipt changed. Reload before continuing")
        state = db.execute(HISTORY_CTE + "SELECT workflow_state FROM history WHERE receipt_id=?", (receipt_id,)).fetchone()[0]
        target, deleted_at, purge_after = 'ACTIVE', None, None
        if request.action == 'RESTORE':
            if row['lifecycle_state'] != 'DELETED':
                raise ReviewConflict("Only deleted receipts can be restored")
            if datetime.fromisoformat(row['purge_after']) <= timestamp:
                raise ReviewConflict("The 30-day restore window has expired")
            if row['content_sha256'] and db.execute("SELECT 1 FROM receipts WHERE content_sha256=? AND lifecycle_state<>'DELETED' AND receipt_id<>?", (row['content_sha256'], receipt_id)).fetchone():
                raise ReviewConflict("An identical retained receipt exists. Open that record instead")
        else:
            if row['lifecycle_state'] != 'ACTIVE':
                raise ReviewConflict("Only active receipts can be deleted or voided")
            accepted = state in ('AUTO_FILED', 'APPROVED', 'AMENDED')
            if request.action == 'VOID':
                if not accepted:
                    raise ReviewConflict("Only auto-filed or approved receipts can be voided")
                target = 'VOIDED'
            else:
                if accepted or state not in ('REVIEW_QUEUE', 'FAILED', 'REJECTED'):
                    raise ReviewConflict("Finalized or processing receipts cannot be deleted")
                target = 'DELETED'
                deleted_at = timestamp.isoformat()
                purge_after = (timestamp + timedelta(days=30)).isoformat()
        event = dict(receipt_id=receipt_id, version=row['lifecycle_version'] + 1,
                     request_id=str(request.request_id), action=request.action,
                     reviewer=request.reviewer, identity_source='self_reported',
                     reason=request.reason, occurred_at=timestamp.isoformat(),
                     before_state=state, state=target, purge_after=purge_after)
        db.execute("UPDATE receipts SET lifecycle_state=?, lifecycle_version=?, deleted_at=?, purge_after=?, updated_at=? WHERE receipt_id=?", (target, event['version'], deleted_at, purge_after, event['occurred_at'], receipt_id))
        db.execute("INSERT INTO lifecycle_events VALUES (?,?,?,?,?)", (receipt_id, event['version'], str(request.request_id), payload, json.dumps(event)))
        return event


def purge_expired(store, upload_dir: Path) -> int:
    """Bounded, retryable cleanup. Never follow a DB-supplied path or delete a void."""
    removed = 0
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT receipt_id FROM receipts r WHERE lifecycle_state='DELETED' AND julianday(purge_after)<=julianday('now') AND NOT EXISTS (SELECT 1 FROM receipt_amendments a WHERE a.receipt_id=r.receipt_id) AND NOT EXISTS (SELECT 1 FROM receipt_reviews v WHERE v.receipt_id=r.receipt_id AND json_extract(v.result_json,'$.decision')='APPROVED') AND NOT EXISTS (SELECT 1 FROM classifications c WHERE c.receipt_id=r.receipt_id AND c.decision='AUTO_FILED') LIMIT 100").fetchall()
        for row in rows:
            receipt_id = str(UUID(row[0]))
            # Keep the DB row on a file failure so the next run can retry safely.
            try:
                for extension in ('.jpg', '.png', '.pdf', '.preview.png'):
                    (upload_dir / (receipt_id + extension)).unlink(missing_ok=True)
            except OSError:
                continue
            for table in ('receipt_payment_events', 'receipt_reprocessing', 'review_audit', 'receipt_reviews', 'line_items', 'classifications', 'lifecycle_events'):
                db.execute(f"DELETE FROM {table} WHERE receipt_id=?", (receipt_id,))
            db.execute("DELETE FROM receipts WHERE receipt_id=?", (receipt_id,))
            removed += 1
    return removed
