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

    def __init__ (self, db_path: str = "temp_database.db"):
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

    _COLLECTION_SCHEMA = {
        "sessions": {
            "game_id": "TEXT",
            "status": "TEXT",
            "lobby_id": "TEXT",
            "created_at": "REAL",
            "version": "INTEGER",
        },
        "actions": {
            "session_id": "TEXT",
            "processed": "INTEGER",
        },
        "rate_limits": {
            "session_id": "TEXT",
            "last_action_at": "REAL",
        },
        "locks": {
            "session_id": "TEXT",
            "version": "INTEGER",
        },
        "nonces": {
            "session_id": "TEXT",
            "player_id": "TEXT",
        },
    }

    def _ensure_table_schema (self, conn, collection: str):
        """
        Ensures the table exists and has all optimized generated columns and indexes.
        """
        # 1. Create base table if needed
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{collection}" (record_id TEXT PRIMARY KEY, timestamp REAL, data TEXT)'
        )

        schema = self._COLLECTION_SCHEMA.get(collection, {})
        if not schema:
            return

        # 2. Check existing columns
        cursor = conn.execute(f'PRAGMA table_info("{collection}")')
        existing_cols = {row["name"] for row in cursor.fetchall()}

        # 3. Add missing generated columns; track which ones are confirmed to exist
        confirmed_cols = set(existing_cols)
        for field, col_type in schema.items():
            if field not in existing_cols:
                try:
                    conn.execute(
                        f'ALTER TABLE "{collection}" ADD COLUMN {field} {col_type} '
                        f'GENERATED ALWAYS AS (json_extract(data, "$.{field}")) VIRTUAL'
                    )
                    confirmed_cols.add(field)
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        confirmed_cols.add(field)
                    else:
                        print(f"Warning: Could not add generated column {field} to {collection}: {e}")

        # 4. Create indexes only for columns confirmed to exist
        for field in schema.keys():
            if field in confirmed_cols:
                conn.execute(
                    f'CREATE INDEX IF NOT EXISTS "idx_{collection}_{field}" ON "{collection}"({field})'
                )

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
                    self._ensure_table_schema(conn, collection)
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

            # Ensure optimized generated columns exist for this collection
            self._ensure_table_schema(conn, collection)

            if expected_version is not None:
                # Use optimized generated column if available, otherwise fallback to json_extract
                schema = self._COLLECTION_SCHEMA.get(collection, {})
                if "version" in schema:
                    where_clause = "version = ?"
                else:
                    where_clause = 'json_extract(data, "$.version") = ?'

                cursor = conn.execute(
                    f'UPDATE "{collection}" SET timestamp = ?, data = ? WHERE record_id = ? AND {where_clause}',
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
        where_sql, params = self._build_filter_clauses(collection, filters)
        
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

            # Ensure optimized generated columns exist for this collection
            self._ensure_table_schema(conn, collection)

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

    def _build_filter_clauses (self, collection: str, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        """
        Translates a filter dict into SQL WHERE clauses using indexed generated columns or json_extract.
        Returns (where_sql, params) — where_sql includes the leading ' WHERE '
        if any filters are present, or an empty string otherwise.
        """
        clauses: list[str] = []
        params: list[Any] = []
        
        col_schema = self._COLLECTION_SCHEMA.get(collection, {})

        for key, value in filters.items():
            sql_op = "="
            field = key
            for suffix, op in self._OPERATORS.items():
                if key.endswith(suffix):
                    sql_op = op
                    field = key[: -len(suffix)]
                    break

            # Optimization: Use record_id for 'id' field, 
            # use generated column if it exists, 
            # otherwise fallback to json_extract.
            if field == "id":
                target_col = "record_id"
            elif field in col_schema:
                target_col = field
            else:
                target_col = f'json_extract(data, "$.{field}")'

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
        SQLITE_VARIABLE_LIMIT = 999

        # Identify if there is a single large '__in' filter that needs chunking.
        in_filter_key: Optional[str] = None
        in_filter_values: list = []
        for key, value in filters.items():
            if key.endswith("__in") and isinstance(value, (list, tuple)) and len(value) > SQLITE_VARIABLE_LIMIT:
                if in_filter_key is not None:
                    # This simple chunking logic supports only one oversized '__in' filter per call.
                    # For more complex scenarios, a more advanced query builder would be needed.
                    in_filter_key = None
                    break
                in_filter_key = key
                in_filter_values = list(value)

        # If no oversized '__in' filter is found, use the standard non-chunked logic.
        if in_filter_key is None:
            where_sql, params = self._build_filter_clauses(collection, filters)

            with self._lock:
                conn = self._get_connection()
                if not self._table_exists(conn, collection):
                    return []

                self._ensure_table_schema(conn, collection)
                cursor = conn.execute(f'SELECT data FROM "{collection}"{where_sql}', params)
                rows = cursor.fetchall()
                deleted = [json.loads(row["data"]) for row in rows]

                if deleted:
                    conn.execute(f'DELETE FROM "{collection}"{where_sql}', params)
                    if not self._in_transaction:
                        conn.commit()
            return deleted

        # --- Chunking Logic ---
        # Handle oversized '__in' filter by splitting it into multiple queries.
        all_deleted = []
        other_filters = filters.copy()
        other_filters.pop(in_filter_key)

        for i in range(0, len(in_filter_values), SQLITE_VARIABLE_LIMIT):
            chunk_values = in_filter_values[i : i + SQLITE_VARIABLE_LIMIT]
            
            current_filters = other_filters.copy()
            current_filters[in_filter_key] = chunk_values
            
            where_sql, params = self._build_filter_clauses(collection, current_filters)
            
            with self._lock:
                conn = self._get_connection()
                if not self._table_exists(conn, collection):
                    continue

                self._ensure_table_schema(conn, collection)

                cursor = conn.execute(f'SELECT data FROM "{collection}"{where_sql}', params)
                rows = cursor.fetchall()
                deleted_chunk = [json.loads(row["data"]) for row in rows]

                if deleted_chunk:
                    conn.execute(f'DELETE FROM "{collection}"{where_sql}', params)
                    if not self._in_transaction:
                        conn.commit()
                
                all_deleted.extend(deleted_chunk)

        return all_deleted

    def query (self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        where_sql, params = self._build_filter_clauses(collection, filters)

        with self._lock:
            conn = self._get_connection()
            if not self._table_exists(conn, collection):
                return []

            # Ensure optimized generated columns exist for this collection
            self._ensure_table_schema(conn, collection)

            cursor = conn.execute(
                f'SELECT data FROM "{collection}"{where_sql}', params
            )
            rows = cursor.fetchall()

        return [json.loads(row["data"]) for row in rows]
