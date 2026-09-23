from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from app.database import DatabaseError, ReceiptStore


def test_concurrent_initialization_and_writes(tmp_path):
    path = tmp_path / "expenses.db"
    def create(i):
        ReceiptStore(path).start(str(i), "image/jpeg", 10, "path", None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(create, range(12)))
    store = ReceiptStore(path)
    assert store.list(None, None, 20, 0)["total"] == 12
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM vendor_category_mappings").fetchone()[0] == 3


def test_seed_is_once_only_and_lookup_is_exact(tmp_path):
    store = ReceiptStore(tmp_path / "expenses.db")
    assert store.lookup_vendor("Teo Heng Stationery & Books").value == "Office Supplies"
    assert store.lookup_vendor("  TEO-HENG stationery & books  ").value == "Office Supplies"
    assert store.lookup_vendor("TEO HENG") is None
    assert store.lookup_vendor("MR D.I.Y. (JOHOR) SDN BHD") is None
    assert store.lookup_vendor("SPOTIFY FAKE") is None
    assert store.lookup_vendor("'; DROP TABLE receipts; --") is None
    with store.connect() as db:
        db.execute("DELETE FROM vendor_category_mappings WHERE vendor_name='SPOTIFY'")
    assert ReceiptStore(store.path).lookup_vendor("SPOTIFY") is None


def test_completion_rollback_and_foreign_keys(tmp_path):
    store = ReceiptStore(tmp_path / "expenses.db")
    store.start("id", "image/jpeg", 10, "private/path", None)
    payload = {"receipt_id": "id", "extracted_data": {"vendor": "Vendor", "line_items": [{"line_total": 1}]},
               "classification": {"workflow_decision": "INVALID"}}
    with pytest.raises(DatabaseError):
        store.complete(payload)
    assert store.get("id")["processing_status"] == "PROCESSING"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM line_items").fetchone()[0] == 0
    with pytest.raises(DatabaseError):
        with store.connect() as db:
            db.execute("INSERT INTO line_items VALUES ('missing', 0, '{}')")
    payload["classification"]["workflow_decision"] = "AUTO_FILED"
    store.complete(payload)
    result = ReceiptStore(store.path).get("id")
    assert result["processing_status"] == "COMPLETED"
    assert result["extracted_data"] == payload["extracted_data"]
    assert "image_path" not in result
    with pytest.raises(DatabaseError):
        store.complete(payload)


def test_newer_schema_is_not_overwritten(tmp_path):
    path = tmp_path / "expenses.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(DatabaseError):
        ReceiptStore(path).get("id")


def test_failure_retains_ocr(tmp_path):
    store = ReceiptStore(tmp_path / "expenses.db")
    store.start("id", "image/jpeg", 10, "private/path", "Office")
    store.save_ocr("id", "Receipt text", "paddle", 0.99)
    store.fail("id", "Receipt extraction timed out")
    result = store.get("id")
    assert result["ocr_text"] == "Receipt text"
    assert result["processing_status"] == "FAILED"
    assert result["classification"] is None
    assert store.list(None, "FAILED", 20, 0)["total"] == 1
