"""SQLite storage for one trusted workspace; no connections span OCR/LLM calls."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from app.classification import DEFAULT_VENDOR_CATEGORIES, ExpenseCategory, normalize_vendor_name


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
            if version in (0, 1):
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
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
            connection.commit()
            with connection:
                yield connection
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseError("Receipt database is unavailable") from exc
        finally:
            if connection is not None:
                connection.close()

    def start(self, receipt_id: str, content_type: str, size: int, image_path: str,
              business_purpose: str | None) -> None:
        timestamp = now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO receipts (receipt_id, content_type, size_bytes, image_path, "
                "business_purpose, processing_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'PROCESSING', ?, ?)",
                (receipt_id, content_type, size, image_path, business_purpose, timestamp, timestamp),
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
            return result

    def list(self, decision: str | None, processing_status: str | None,
             limit: int, offset: int) -> dict:
        where = " WHERE (? IS NULL OR c.decision=?) AND (? IS NULL OR r.processing_status=?)"
        args = (decision, decision, processing_status, processing_status)
        source = " FROM receipts r LEFT JOIN classifications c USING(receipt_id)"
        with self.connect() as db:
            # Keep count and page in the same read snapshot.
            db.execute("BEGIN")
            total = db.execute("SELECT count(*)" + source + where, args).fetchone()[0]
            rows = db.execute("SELECT r.receipt_id, r.content_type, r.size_bytes, "
                              "r.processing_status, r.created_at, r.updated_at, c.decision"
                              + source + where + " ORDER BY r.created_at DESC, r.receipt_id DESC LIMIT ? OFFSET ?",
                              args + (limit, offset)).fetchall()
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
