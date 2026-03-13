import threading
import time
import pytest
import os
from local.sql_database import SQLiteDatabase

def test_sqlite_cas_concurrency ():
    import uuid
    db_path = f"test_cas_{uuid.uuid4().hex}.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    db = SQLiteDatabase(db_path)
    collection = "test_collection"
    record_id = "rec_1"
    
    # Initial record
    db.create(collection, {"id": record_id, "version": 0, "value": 0})
    
    num_threads = 10
    success_count = [0]
    lock = threading.Lock()
    
    def worker ():
        # Try to increment the value exactly once
        # In a real scenario, matchmaking would retry. Here we just want to see if CAS works.
        # We'll retry up to 100 times to ensure we actually hit a race.
        for _ in range(100):
            data = db.read(collection, record_id)
            if not data:
                continue
            
            current_version = data["version"]
            data["version"] = current_version + 1
            data["value"] += 1
            
            if db.update(collection, record_id, data, expected_version=current_version):
                with lock:
                    success_count[0] += 1
                break
            # If update fails, we just retry by reading again
    
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    final_data = db.read(collection, record_id)
    
    assert final_data is not None, f"Record {record_id} not found in {collection}"
    assert final_data["value"] == num_threads
    assert final_data["version"] == num_threads
    assert success_count[0] == num_threads
    
    db.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)

if __name__ == "__main__":
    test_sqlite_cas_concurrency()
