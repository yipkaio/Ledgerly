"""Audited extraction drafts from immutable saved OCR; never auto-approve."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.review import ReviewConflict, ReviewNotFound, reject_placeholder


class ReprocessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_record_version: Annotated[int, Field(strict=True, ge=0)]
    expected_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    reviewer: Annotated[str, Field(min_length=1, max_length=100)]
    reason: Annotated[str, Field(min_length=10, max_length=2000)]

    @field_validator('reviewer', 'reason')
    @classmethod
    def valid_text(cls, value):
        reject_placeholder(value)
        return value


REPROCESS_SCHEMA = (
    "CREATE TABLE receipt_reprocessing (request_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id), request_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCEEDED','FAILED','SUPERSEDED')), started_at TEXT NOT NULL, expires_at TEXT NOT NULL, result_json TEXT NOT NULL)",
    "CREATE UNIQUE INDEX one_reprocess_running ON receipt_reprocessing(receipt_id) WHERE status='RUNNING'",
    "CREATE INDEX reprocess_history ON receipt_reprocessing(receipt_id, started_at)",
    "CREATE TRIGGER reprocess_final_no_update BEFORE UPDATE ON receipt_reprocessing WHEN OLD.status<>'RUNNING' BEGIN SELECT RAISE(ABORT, 'Immutable reprocessing history'); END",
    "CREATE TRIGGER reprocess_no_delete BEFORE DELETE ON receipt_reprocessing WHEN NOT EXISTS (SELECT 1 FROM receipts WHERE receipt_id=OLD.receipt_id AND lifecycle_state='DELETED' AND julianday(purge_after)<=julianday('now')) BEGIN SELECT RAISE(ABORT, 'Immutable reprocessing history'); END",
)


def record_version(db, rid):
    return db.execute('SELECT count(*) FROM receipt_reviews WHERE receipt_id=?', (rid,)).fetchone()[0] + db.execute('SELECT count(*) FROM receipt_amendments WHERE receipt_id=?', (rid,)).fetchone()[0]


def validate_source(db, rid, request_id):
    if request_id is None:
        return
    row = db.execute("SELECT 1 FROM receipt_reprocessing WHERE receipt_id=? AND request_id=? AND status='SUCCEEDED'", (rid, str(request_id))).fetchone()
    if not row:
        raise ReviewConflict('Reprocessing draft is unavailable for this receipt')


def begin(store, rid, request, model):
    payload = json.dumps(request.model_dump(mode='json'), sort_keys=True)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        now = datetime.now(timezone.utc)
        # A process crash never causes the same request to spend credits again.
        for old in db.execute("SELECT * FROM receipt_reprocessing WHERE receipt_id=? AND status='RUNNING' AND expires_at<=?", (rid, now.isoformat())).fetchall():
            result = json.loads(old['result_json'])
            result.update(status='FAILED', error='Processing was interrupted. Start a new attempt if needed.')
            db.execute("UPDATE receipt_reprocessing SET status='FAILED', result_json=? WHERE request_id=?", (json.dumps(result), old['request_id']))
        prior = db.execute('SELECT * FROM receipt_reprocessing WHERE request_id=?', (str(request.request_id),)).fetchone()
        if prior:
            if prior['receipt_id'] != rid or prior['request_json'] != payload:
                raise ReviewConflict('Request ID already used with different content')
            return json.loads(prior['result_json']), None
        row = db.execute('SELECT * FROM receipts WHERE receipt_id=?', (rid,)).fetchone()
        if row is None:
            raise ReviewNotFound('Receipt not found')
        review = db.execute('SELECT result_json FROM receipt_reviews WHERE receipt_id=?', (rid,)).fetchone()
        if row['lifecycle_state'] != 'ACTIVE' or row['processing_status'] == 'PROCESSING' or (review and json.loads(review[0])['decision'] == 'REJECTED'):
            raise ReviewConflict('Only active, non-rejected receipts can be reprocessed')
        if not (row['ocr_text'] or '').strip():
            raise ReviewConflict('No saved OCR text is available. Upload a new readable receipt instead')
        if row['lifecycle_version'] != request.expected_lifecycle_version or record_version(db, rid) != request.expected_record_version:
            raise ReviewConflict('Receipt changed. Reload before reprocessing')
        if db.execute("SELECT 1 FROM receipt_reprocessing WHERE receipt_id=? AND status='RUNNING'", (rid,)).fetchone():
            raise ReviewConflict('Reprocessing is already running. Reload to check its progress')
        result = dict(request_id=str(request.request_id), receipt_id=rid, reviewer=request.reviewer,
                      identity_source='self_reported', reason=request.reason, started_at=now.isoformat(),
                      expires_at=(now + timedelta(minutes=10)).isoformat(), status='RUNNING',
                      source='saved_ocr', model=model, before_processing_status=row['processing_status'],
                      extracted_data=None, error=None)
        db.execute('INSERT INTO receipt_reprocessing VALUES (?,?,?,?,?,?,?)', (result['request_id'], rid, payload, 'RUNNING', result['started_at'], result['expires_at'], json.dumps(result)))
        return result, row['ocr_text']


def finish(store, rid, request, data=None, error=None):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        attempt = db.execute('SELECT * FROM receipt_reprocessing WHERE request_id=?', (str(request.request_id),)).fetchone()
        if attempt is None:
            raise ReviewNotFound('Reprocessing record unavailable')
        if attempt['status'] != 'RUNNING':
            return json.loads(attempt['result_json'])
        row = db.execute('SELECT * FROM receipts WHERE receipt_id=?', (rid,)).fetchone()
        result = json.loads(attempt['result_json'])
        changed = row is None or row['lifecycle_state'] != 'ACTIVE' or row['lifecycle_version'] != request.expected_lifecycle_version or record_version(db, rid) != request.expected_record_version
        result.update(status='SUPERSEDED' if changed else 'FAILED' if error else 'SUCCEEDED',
                      extracted_data=data, error=error, finished_at=datetime.now(timezone.utc).isoformat())
        db.execute('UPDATE receipt_reprocessing SET status=?, result_json=? WHERE request_id=?', (result['status'], json.dumps(result), result['request_id']))
        if result['status'] == 'SUCCEEDED' and row['processing_status'] == 'FAILED':
            # Original OCR/extraction/error stay untouched. Recovery requires review.
            db.execute("UPDATE receipts SET processing_status='REVIEW_QUEUE', updated_at=? WHERE receipt_id=?", (result['finished_at'], rid))
        return result


async def reprocess(store, rid, request, extractor, model):
    result, text = await run_in_threadpool(begin, store, rid, request, model)
    if text is None:
        return result
    try:
        # Bound the run below the durable 10-minute lease.
        data = await asyncio.wait_for(extractor.extract(text), timeout=180)
        return await run_in_threadpool(finish, store, rid, request, data.model_dump(mode='json'))
    except asyncio.CancelledError:
        await run_in_threadpool(finish, store, rid, request, None, 'Processing was interrupted. Start a new attempt if needed.')
        raise
    except Exception:
        return await run_in_threadpool(finish, store, rid, request, None, 'Extraction failed. Original evidence is unchanged. Start a new attempt to try again.')
