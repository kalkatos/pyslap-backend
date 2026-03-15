import os
import tempfile
import pytest
from local.sql_database import SQLiteDatabase

def test_sqlite_transaction_commit ():
    db_path = tempfile.mktemp(suffix=".db")
    db = SQLiteDatabase(db_path)
    try:
        db.start_transaction()
        db.create("test_coll", {"id": "rec1", "val": 100})
        db.create("test_coll", {"id": "rec2", "val": 200})
        db.commit()

        assert db.read("test_coll", "rec1")["val"] == 100
        assert db.read("test_coll", "rec2")["val"] == 200
    finally:
        db.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)

def test_sqlite_transaction_rollback ():
    db_path = tempfile.mktemp(suffix=".db")
    db = SQLiteDatabase(db_path)
    try:
        # 1. Successful write
        db.create("test_coll", {"id": "existing", "val": 0})
        
        # 2. Start transaction and attempt multi-write
        db.start_transaction()
        db.update("test_coll", "existing", {"id": "existing", "val": 1})
        db.create("test_coll", {"id": "new_rec", "val": 2})
        
        # 3. Rollback
        db.rollback()

        # 4. Verify original state
        assert db.read("test_coll", "existing")["val"] == 0
        assert db.read("test_coll", "new_rec") is None
    finally:
        db.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)

def test_sqlite_transaction_lock_concurrency ():
    import threading
    import time

    db_path = tempfile.mktemp(suffix=".db")
    db = SQLiteDatabase(db_path)
    
    results = {"started": False, "finished": False}

    def other_thread_task ():
        # This should block until the transaction is committed
        results["started"] = True
        db.read("test_coll", "rec1")
        results["finished"] = True

    try:
        db.start_transaction()
        db.create("test_coll", {"id": "rec1", "val": 100})
        
        t = threading.Thread(target=other_thread_task)
        t.start()
        
        time.sleep(0.1)
        assert results["started"] is True
        assert results["finished"] is False # Lock held by transaction
        
        db.commit()
        t.join(timeout=1)
        assert results["finished"] is True
    finally:
        db.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)
