"""SQLite storage for one trusted workspace; no connections span OCR/LLM calls."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from app.classification import DEFAULT_VENDOR_CATEGORIES, ExpenseCategory, normalize_vendor_name
from app.history import HISTORY_COLUMNS, HISTORY_CTE, HistoryFilters, filter_clause


class DuplicateReceiptError(RuntimeError):
    """An identical file is already retained in this workspace."""

    def __init__(self, receipt_id: str):
        super().__init__("Receipt file was already uploaded")
        self.receipt_id = receipt_id


class DatabaseError(RuntimeError):
    """A safe persistence failure; never expose SQLite details to callers."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReceiptStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            # Serialize first-use schema creation, without write-locking normal reads.
            if version in (0, 1, 2, 3, 4, 5, 6, 7):
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8):
                raise DatabaseError("Unsupported database schema version")
            if version == 0:
                for statement in SCHEMA:
                    connection.execute(statement)
                connection.executemany(
                    "INSERT INTO vendor_category_mappings VALUES (?, ?)",
                    [(name, category.value) for name, category in DEFAULT_VENDOR_CATEGORIES.items()],
                )
                connection.execute("PRAGMA user_version=1")
            if version in (0, 1):
                from app.review import REVIEW_SCHEMA
                for statement in REVIEW_SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=2")
            if version in (0, 1, 2):
                from app.amendments import AMENDMENT_SCHEMA
                for statement in DUPLICATE_SCHEMA + AMENDMENT_SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=3")
            if version in (0, 1, 2, 3):
                from app.lifecycle import LIFECYCLE_SCHEMA
                for statement in LIFECYCLE_SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=4")
            if version in (0, 1, 2, 3, 4):
                from app.reprocessing import REPROCESS_SCHEMA
                for statement in REPROCESS_SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=5")
            if version in (0, 1, 2, 3, 4, 5):
                from app.statements import STATEMENT_SCHEMA
                for statement in STATEMENT_SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=6")
            if version in (0, 1, 2, 3, 4, 5, 6):
                from app.fx import FX_SCHEMA
                for statement in FX_SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=7")
            if version in (0, 1, 2, 3, 4, 5, 6, 7):
                from app.statements import STATEMENT_MIGRATION_8
                for statement in STATEMENT_MIGRATION_8:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=8")
            connection.commit()
            with connection:
                yield connection
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseError("Receipt database is unavailable") from exc
        finally:
            if connection is not None:
                connection.close()

    def start(self, receipt_id: str, content_type: str, size: int, image_path: str,
              business_purpose: str | None, content_sha256: str | None = None) -> None:
        timestamp = now()
        with self.connect() as db:
            try:
                db.execute(
                    "INSERT INTO receipts (receipt_id, content_type, size_bytes, image_path, "
                    "business_purpose, content_sha256, processing_status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'PROCESSING', ?, ?)",
                    (receipt_id, content_type, size, image_path, business_purpose,
                     content_sha256, timestamp, timestamp),
                )
            except sqlite3.IntegrityError:
                duplicate = db.execute(
                    "SELECT receipt_id FROM receipts WHERE content_sha256=? AND lifecycle_state<>'DELETED'",
                    (content_sha256,),
                ).fetchone()
                if duplicate:
                    raise DuplicateReceiptError(duplicate[0])
                raise

    def probable_duplicates(self, receipt_id: str, extraction: dict) -> list[str]:
        """Return strict identity matches; vendor+amount alone are never enough."""
        required = (extraction.get("receipt_number"), extraction.get("date"),
                    extraction.get("currency"), extraction.get("total_amount"))
        vendor = extraction.get("vendor") or extraction.get("legal_entity")
        if any(value is None for value in required) or not vendor:
            return []
        with self.connect() as db:
            rows = db.execute(
                "SELECT receipt_id, extraction_json FROM receipts "
                "WHERE receipt_id<>? AND lifecycle_state='ACTIVE' AND extraction_json IS NOT NULL "
                "AND lower(trim(json_extract(extraction_json,'$.receipt_number')))=lower(trim(?)) "
                "AND json_extract(extraction_json,'$.date')=? "
                "AND json_extract(extraction_json,'$.currency')=? "
                "AND abs(json_extract(extraction_json,'$.total_amount')-?)<=0.02 "
                "ORDER BY created_at LIMIT 20",
                (receipt_id, str(required[0]), str(required[1]), str(required[2]),
                 float(required[3])),
            ).fetchall()
        wanted = normalize_vendor_name(vendor)
        matches = []
        for row in rows:
            candidate = json.loads(row[1])
            candidate_vendor = candidate.get("vendor") or candidate.get("legal_entity") or ""
            if normalize_vendor_name(candidate_vendor) == wanted:
                matches.append(row[0])
        return matches

    def save_duplicate_candidates(self, receipt_id: str, candidates: list[str]) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE receipts SET duplicate_candidates_json=?, updated_at=? WHERE receipt_id=?",
                (json.dumps(candidates), now(), receipt_id),
            )

    def save_ocr(self, receipt_id: str, text: str, engine: str, confidence: float | None) -> None:
        with self.connect() as db:
            db.execute("UPDATE receipts SET ocr_text=?, ocr_engine=?, ocr_confidence=?, "
                       "updated_at=? WHERE receipt_id=?",
                       (text, engine, confidence, now(), receipt_id))

    def lookup_vendor(self, vendor: str | None) -> ExpenseCategory | None:
        if not vendor:
            return None
        with self.connect() as db:
            row = db.execute("SELECT category FROM vendor_category_mappings WHERE vendor_name=?",
                             (normalize_vendor_name(vendor),)).fetchone()
        try:
            return ExpenseCategory(row[0]) if row else None
        except ValueError as exc:
            raise DatabaseError("Invalid vendor mapping") from exc

    def complete(self, payload: dict) -> None:
        receipt_id = payload['receipt_id']
        extraction = dict(payload['extracted_data'])
        items = extraction.pop('line_items')
        classification = payload['classification']
        state = 'REVIEW_QUEUE' if classification['workflow_decision'] == 'REVIEW_QUEUE' else 'COMPLETED'
        with self.connect() as db:
            db.execute("UPDATE receipts SET processing_status=?, extraction_json=?, updated_at=? "
                       "WHERE receipt_id=? AND processing_status='PROCESSING'",
                       (state, json.dumps(extraction, allow_nan=False), now(), receipt_id))
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise DatabaseError("Receipt is not processing")
            db.executemany("INSERT INTO line_items VALUES (?, ?, ?)",
                           [(receipt_id, i, json.dumps(item, allow_nan=False)) for i, item in enumerate(items)])
            db.execute("INSERT INTO classifications VALUES (?, ?, ?)",
                       (receipt_id, classification['workflow_decision'], json.dumps(classification, allow_nan=False)))

    def fail(self, receipt_id: str, reason: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE receipts SET processing_status='FAILED', error=?, updated_at=? "
                       "WHERE receipt_id=? AND processing_status='PROCESSING'",
                       (reason, now(), receipt_id))

    def get(self, receipt_id: str) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result.pop('image_path')  # Internal filesystem paths must never leave the API.
            raw = result.pop('extraction_json')
            result['extracted_data'] = json.loads(raw) if raw else None
            if raw:
                result['extracted_data']['line_items'] = [json.loads(item[0]) for item in db.execute(
                    "SELECT item_json FROM line_items WHERE receipt_id=? ORDER BY position", (receipt_id,))]
            classification = db.execute("SELECT result_json FROM classifications WHERE receipt_id=?", (receipt_id,)).fetchone()
            result['classification'] = json.loads(classification[0]) if classification else None
            review = db.execute("SELECT result_json FROM receipt_reviews WHERE receipt_id=?", (receipt_id,)).fetchone()
            result['review'] = json.loads(review[0]) if review else None
            result['review_version'] = 1 if review else 0
            candidates = result.pop('duplicate_candidates_json', None)
            result['duplicate_candidates'] = json.loads(candidates) if candidates else []
            amendment = db.execute(
                "SELECT result_json FROM receipt_amendments WHERE receipt_id=? "
                "ORDER BY version DESC LIMIT 1", (receipt_id,)
            ).fetchone()
            result['amendment'] = json.loads(amendment[0]) if amendment else None
            result['record_version'] = (1 if review else 0) + db.execute(
                "SELECT count(*) FROM receipt_amendments WHERE receipt_id=?", (receipt_id,)
            ).fetchone()[0]
            if result['amendment']:
                result['effective_data'] = result['amendment']['final_data']
                result['effective_category'] = result['amendment']['category']
            elif result['review'] and result['review']['decision'] == 'APPROVED':
                result['effective_data'] = result['review']['final_data']
                result['effective_category'] = result['review']['category']
            else:
                result['effective_data'] = result['extracted_data']
                result['effective_category'] = (result['classification'] or {}).get('category')
            result['lifecycle_events'] = [json.loads(event[0]) for event in db.execute(
                "SELECT event_json FROM lifecycle_events WHERE receipt_id=? ORDER BY version", (receipt_id,))]
            result['reprocessing'] = [json.loads(event[0]) for event in db.execute(
                "SELECT result_json FROM receipt_reprocessing WHERE receipt_id=? ORDER BY started_at DESC", (receipt_id,))]
            result['payment_events'] = [json.loads(event[0]) for event in db.execute(
                "SELECT result_json FROM receipt_payment_events WHERE receipt_id=? ORDER BY version DESC", (receipt_id,))]
            return result

    def list(self, decision: str | None, processing_status: str | None,
             limit: int, offset: int, filters: HistoryFilters | None = None) -> dict:
        filters = filters or HistoryFilters()
        where, args = filter_clause(filters)
        legacy = []
        if decision is not None:
            legacy.append("decision=?")
            args += (decision,)
        if processing_status is not None:
            legacy.append("processing_status=?")
            args += (processing_status,)
        if legacy:
            where += (" AND " if where else " WHERE ") + " AND ".join(legacy)
        with self.connect() as db:
            # Keep count and page in the same read snapshot.
            db.execute("BEGIN")
            total = db.execute(HISTORY_CTE + "SELECT count(*) FROM history" + where, args).fetchone()[0]
            rows = db.execute(
                HISTORY_CTE + "SELECT " + HISTORY_COLUMNS + " FROM history" + where
                + " ORDER BY created_at DESC, receipt_id DESC LIMIT ? OFFSET ?",
                args + (limit, offset),
            ).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}


SCHEMA = (
    "CREATE TABLE receipts (receipt_id TEXT PRIMARY KEY, content_type TEXT NOT NULL, "
    "size_bytes INTEGER NOT NULL CHECK(size_bytes>0), image_path TEXT NOT NULL, "
    "business_purpose TEXT, processing_status TEXT NOT NULL CHECK(processing_status IN "
    "('PROCESSING','COMPLETED','REVIEW_QUEUE','FAILED')), created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, ocr_text TEXT, ocr_engine TEXT, ocr_confidence REAL, "
    "extraction_json TEXT, error TEXT)",
    "CREATE TABLE line_items (receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id), "
    "position INTEGER NOT NULL CHECK(position>=0), item_json TEXT NOT NULL, PRIMARY KEY(receipt_id, position))",
    "CREATE TABLE classifications (receipt_id TEXT PRIMARY KEY REFERENCES receipts(receipt_id), "
    "decision TEXT NOT NULL CHECK(decision IN ('AUTO_FILED','REVIEW_QUEUE')), result_json TEXT NOT NULL)",
    "CREATE TABLE vendor_category_mappings (vendor_name TEXT PRIMARY KEY, category TEXT NOT NULL)",
    "CREATE INDEX receipt_history ON receipts(created_at DESC, receipt_id DESC)",
    "CREATE INDEX receipt_status ON receipts(processing_status)",
    "CREATE INDEX classification_decision ON classifications(decision)",
)

DUPLICATE_SCHEMA = (
    "ALTER TABLE receipts ADD COLUMN content_sha256 TEXT",
    "ALTER TABLE receipts ADD COLUMN duplicate_candidates_json TEXT",
    "CREATE UNIQUE INDEX exact_receipt_content ON receipts(content_sha256) "
    "WHERE content_sha256 IS NOT NULL",
)
