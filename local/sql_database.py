import sqlite3
import json
import uuid
from typing import Any, Optional

from pyslap.interfaces.database import DatabaseInterface

class SQLiteDatabase(DatabaseInterface):
    """
    A SQLite implementation of DatabaseInterface for local testing.
    Stores all collections in a single 'records' table with JSON data.
    """
    
    def __init__(self, db_path: str = "local_pyslap.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes the generic records table if it doesn't exist."""
        conn = self._get_connection()
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS records (
                    collection TEXT,
                    record_id TEXT,
                    data TEXT,
                    PRIMARY KEY (collection, record_id)
                )
            ''')
            conn.commit()
        finally:
            conn.close()

    def create(self, collection: str, data: dict[str, Any]) -> str:
        # Use an existing id if provided, otherwise generate a new one
        record_id = data.get("id", str(uuid.uuid4()))
        if "id" not in data:
            data["id"] = record_id

        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO records (collection, record_id, data) VALUES (?, ?, ?)",
                (collection, record_id, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

        return record_id

    def read(self, collection: str, record_id: str) -> Optional[dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT data FROM records WHERE collection = ? AND record_id = ?",
                (collection, record_id)
            )
            row = cursor.fetchone()

            if row:
                return json.loads(row['data'])
            return None
        finally:
            conn.close()

    def update(self, collection: str, record_id: str, data: dict[str, Any]) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "UPDATE records SET data = ? WHERE collection = ? AND record_id = ?",
                (json.dumps(data), collection, record_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, collection: str, record_id: str) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM records WHERE collection = ? AND record_id = ?",
                (collection, record_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def query(self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        # For a local mock DB, it's safer to fetch all collection items
        # and filter in Python rather than dealing with SQLite JSON intricacies.
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT data FROM records WHERE collection = ?", 
                (collection,)
            )

            results = []
            for row in cursor.fetchall():
                data = json.loads(row['data'])

                # Check if all filters match
                match = True
                for key, value in filters.items():
                    if data.get(key) != value:
                        match = False
                        break

                if match:
                    results.append(data)

            return results
        finally:
            conn.close()
