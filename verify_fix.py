import os
import sys
import time
import uuid
import json

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from local.sql_database import SQLiteDatabase
from local.local_server import LocalScheduler
from pyslap.core.engine import PySlapEngine
from games.rps import RpsGameRules
from pyslap.models.domain import SessionStatus

import asyncio

async def verify():
    db_path = "test_serialization.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    db = SQLiteDatabase(db_path=db_path)
    scheduler = LocalScheduler()
    engine = PySlapEngine(
        db=db,
        scheduler=scheduler,
        games_registry={"rps": RpsGameRules()},
    )

    print("Attempting to create session (this triggers serialization)...")
    try:
        result = engine.create_session("rps", "player1", "Player")
        print("Session created successfully!")
        
        session_id = result["session_id"]
        
        # Verify it was saved correctly as JSON in SQLite
        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT data FROM records WHERE collection = 'sessions' AND record_id = ?", (session_id,))
            row = cursor.fetchone()
            data = json.loads(row[0])
            print(f"Stored session status: {data['status']} (type: {type(data['status'])})")
            assert data['status'] == "active"
            
            # Verify nested objects (players)
            assert "player1" in data["players"]
            assert data["players"]["player1"]["name"] == "Player"
            print("Nested objects (players) serialized correctly!")
            
        finally:
            conn.close()

    except Exception as e:
        print(f"FAILED with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

if __name__ == "__main__":
    asyncio.run(verify())
