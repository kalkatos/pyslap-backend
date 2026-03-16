import sqlite3
import threading
import json
import uuid
import os
import time
from typing import Any, Optional

from pyslap.interfaces.database import DatabaseInterface


class SQLiteDatabase(DatabaseInterface):
    """
    A SQLite implementation of DatabaseInterface for local testing.
    Stores each collection in its own table with JSON data.
    """

    def __init__ (self, db_path: str = "temp_database"):
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._in_transaction = False
        self._init_db()

    def _get_connection (self):
        return self._conn

    def _table_exists (self, conn, table_name: str) -> bool:
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False

    def _init_db (self):
        """No generic tables to initialize upfront."""
        pass

    def start_transaction (self) -> None:
        self._lock.acquire()
        self._in_transaction = True
        self._conn.execute("BEGIN TRANSACTION")

    def commit (self) -> None:
        if not self._in_transaction:
            return
        try:
            self._conn.commit()
        finally:
            self._in_transaction = False
            self._lock.release()

    def rollback (self) -> None:
        if not self._in_transaction:
            return
        try:
            self._conn.rollback()
        finally:
            self._in_transaction = False
            self._lock.release()

    def dispose (self):
        self._conn.close()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def create (self, collection: str, data: dict[str, Any], fail_if_exists: bool = False) -> Optional[str]:
        # Use an existing id if provided, otherwise generate a new one
        record_id = data.get("id", str(uuid.uuid4()))
        if "id" not in data:
            data["id"] = record_id

        insert_sql = 'INSERT INTO' if fail_if_exists else 'INSERT OR REPLACE INTO'

        with self._lock:
            conn = self._get_connection()
            # Retry loop for potential locked database
            for _ in range(5):
                try:
                    conn.execute(
                        f'CREATE TABLE IF NOT EXISTS "{collection}" (record_id TEXT PRIMARY KEY, timestamp REAL, data TEXT)'
                    )
                    conn.execute(
                        f'{insert_sql} "{collection}" (record_id, timestamp, data) VALUES (?, ?, ?)',
                        (record_id, time.time(), json.dumps(data)),
                    )
                    if not self._in_transaction:
                        conn.commit()
                    return record_id
                except sqlite3.IntegrityError:
                    # fail_if_exists=True and a record with this id already exists
                    return None
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        time.sleep(0.05)
                        continue
                    raise

        return record_id

    def read (self, collection: str, record_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            if not self._table_exists(conn, collection):
                return None

            cursor = conn.execute(
                f'SELECT data FROM "{collection}" WHERE record_id = ?', (record_id,)
            )
            row = cursor.fetchone()

        if row:
            return json.loads(row["data"])
        return None

    def update (self, collection: str, record_id: str, data: dict[str, Any],
                expected_version: Optional[int] = None) -> bool:
        with self._lock:
            conn = self._get_connection()
            if not self._table_exists(conn, collection):
                return False

            if expected_version is not None:
                # Use SQLite's json_extract to check the version in the JSON data column atomically
                cursor = conn.execute(
                    f'UPDATE "{collection}" SET timestamp = ?, data = ? WHERE record_id = ? AND json_extract(data, "$.version") = ?',
                    (time.time(), json.dumps(data), record_id, expected_version),
                )
            else:
                cursor = conn.execute(
                    f'UPDATE "{collection}" SET timestamp = ?, data = ? WHERE record_id = ?',
                    (time.time(), json.dumps(data), record_id),
                )
            
            if not self._in_transaction:
                conn.commit()
            return cursor.rowcount > 0

    def conditional_update (self, collection: str, record_id: str, data: dict[str, Any],
                           filters: dict[str, Any]) -> bool:
        where_sql, params = self._build_filter_clauses(filters)
        
        # Ensure record_id is included in the condition
        if not where_sql:
            where_sql = " WHERE record_id = ?"
        else:
            # We assume the filters don't already include record_id matching logic for now, 
            # or if they do, we append it.
            where_sql += " AND record_id = ?"
        params.append(record_id)

        with self._lock:
            conn = self._get_connection()
            if not self._table_exists(conn, collection):
                return False

            cursor = conn.execute(
                f'UPDATE "{collection}" SET timestamp = ?, data = ?{where_sql}',
                [time.time(), json.dumps(data), *params],
            )
            
            if not self._in_transaction:
                conn.commit()
            return cursor.rowcount > 0

    def delete (self, collection: str, record_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            if not self._table_exists(conn, collection):
                return False

            cursor = conn.execute(
                f'DELETE FROM "{collection}" WHERE record_id = ?', (record_id,)
            )
            if not self._in_transaction:
                conn.commit()
            return cursor.rowcount > 0

    # Operator suffixes supported by delete_by_filter and _build_filter_clauses
    _OPERATORS = {"__lt": "<", "__lte": "<=", "__gt": ">", "__gte": ">=", "__ne": "!=", "__in": "IN"}

    def _build_filter_clauses (self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        """
        Translates a filter dict into SQL WHERE clauses using json_extract.
        Returns (where_sql, params) — where_sql includes the leading ' WHERE '
        if any filters are present, or an empty string otherwise.
        """
        clauses: list[str] = []
        params: list[Any] = []

        for key, value in filters.items():
            sql_op = "="
            field = key
            for suffix, op in self._OPERATORS.items():
                if key.endswith(suffix):
                    sql_op = op
                    field = key[: -len(suffix)]
                    break

            # Use indexed record_id column for 'id' field for performance
            target_col = "record_id" if field == "id" else f'json_extract(data, "$.{field}")'

            if sql_op == "IN":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                if not value:
                    # Handle empty IN list: should never match anything
                    clauses.append("1 = 0")
                else:
                    placeholders = ",".join(["?"] * len(value))
                    clauses.append(f'{target_col} IN ({placeholders})')
                    params.extend(value)
            elif value is None:
                clauses.append(f"{target_col} IS NULL" if sql_op == "=" else f"{target_col} IS NOT NULL")
            else:
                clauses.append(f"{target_col} {sql_op} ?")
                params.append(value)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where_sql, params

    def delete_by_filter (self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where_sql, params = self._build_filter_clauses(filters)

        with self._lock:
            conn = self._get_connection()
            if not self._table_exists(conn, collection):
                return []

            # Fetch matching rows first so we can return them
            cursor = conn.execute(
                f'SELECT data FROM "{collection}"{where_sql}', params
            )
            rows = cursor.fetchall()
            deleted = [json.loads(row["data"]) for row in rows]

            if deleted:
                conn.execute(
                    f'DELETE FROM "{collection}"{where_sql}', params
                )
                if not self._in_transaction:
                    conn.commit()

        return deleted

    def query (self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where_sql, params = self._build_filter_clauses(filters)

        with self._lock:
            conn = self._get_connection()
            if not self._table_exists(conn, collection):
                return []

            cursor = conn.execute(
                f'SELECT data FROM "{collection}"{where_sql}', params
            )
            rows = cursor.fetchall()

        return [json.loads(row["data"]) for row in rows]
