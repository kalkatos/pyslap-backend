# PySlap Roadmap & Technical Implementation Guide

This document provides technical blueprints for future PySlap enhancements. Refer to these items for subsequent development phases.

## **Important**: For any of these changes, no new entrypoint should be created, only if stricly necessary to avoid security risks or poor performance.

Features already done are marked with ✅DONE

---

## ✨ Feature Improvements

### 1. Spectator Mode
*   **Description**: Support users watching matches without participating.
*   **Changes**:
    *   Update `PySlapEngine.register_action` to allow joining sessions beyond the `max_players` limit if the role is `SPECTATOR`.
    *   Update `GameRules.to_player_state` to ensure spectators receive the full public state but no private data.
*   **Testing**: Join a match with 2 players and 1 spectator. Verify the spectator sees updates but cannot move.

### 2. Match Replay & History
*   **Description**: Record the sequence of actions and state transitions to allow post-game review.
*   **Changes**:
    *   Add an `action_history` collection to the database.
    *   Update the engine to archive the full state and action logs when a session terminates.
*   **Testing**: Play a full match, then use a script to fetch the history and verify every move is logged in order.

### 3. Global Leaderboards
*   **Description**: Track player wins and losses across all sessions and games.
*   **Changes**:
    *   Implement a `player_stats` collection in the database.
    *   Update the engine to report winners to the database when a game ends.
*   **Testing**: Play multiple matches as the same player and verify the win count increments in the DB.

### 4. In-Game Chat System
*   **Description**: Simple text communication between players during active sessions.
*   **Changes**:
    *   Add a `chat` action type to the engine.
    *   Store messages in a `messages` list within the `public_state` for real-time syncing.
*   **Testing**: Send a chat action from one client and verify it appears in the display of the other client.

---

## 🛠️ Infrastructure & Stability Fixes

### ✅DONE 20. Atomic Distributed Locking
*   **Description**: Fix the `_try_acquire_loop_lock` create-race where multiple instances can claim the same lock simultaneously.
*   **Changes**:
    *   Update `DatabaseInterface.create` to support a `fail_if_exists` parameter.
    *   Modify `PySlapEngine._try_acquire_loop_lock` to use this flag during lock creation.
*   **Testing**: Run stress tests with multiple concurrent `process_update_loop` calls for the same session; verify only one succeeds in entering the execution block.

### ✅DONE 21. Database Transaction Support
*   **Description**: Ensure that updates involving multiple records (e.g., Session and GameState) are atomic.
*   **Changes**:
    *   Add `start_transaction`, `commit`, and `rollback` methods to `DatabaseInterface`.
    *   Update `PySlapEngine.create_session` and `_execute_update_loop` to wrap multi-collection updates in transactions.
*   **Testing**: Simulate a crash/failure between the Session and State update; verify that neither record is updated (rollback).

### ✅DONE 22. Scalable Matchmaking
*   **Description**: Prevent database "thundering herd" load when many players attempt to join the same matchmaking sessions.
*   **Changes**:
    *   Implement a "CLAIMED" status for sessions or a separate matchmaking queue.
    *   Modify `create_session` to use a more efficient lookup and lock mechanism for joining sessions.
*   **Testing**: Use a load-testing script to simulate 100+ players joining simultaneously; verify database query counts remain linear rather than exponential.

### ✅DONE 23. Atomic Player Rate Limiting
*   **Description**: Prevent players from bypassing rate limits by sending multiple concurrent actions.
*   **Changes**:
    *   Refactor `Validator.validate_action_rate` and `record_action_rate` into a single atomic database operation (e.g., using `UPDATE ... WHERE last_action < current - gap`).
*   **Testing**: Send 10 identical move actions at the same microsecond; verify only one is accepted.

### ✅DONE 24. Batch Maintenance Operations
*   **Description**: Optimize `cleanup_old_records` to handle large volumes of expired sessions without blocking.
*   **Changes**:
    *   Replace sequential per-session loops with batch delete operations using `db.delete_by_filter`.
*   **Testing**: Populate the DB with 10,000 expired sessions and verify cleanup completes in seconds rather than minutes.

### ✅DONE 25. Security Hardening
*   **Description**: Reduce the exploit surface of debugging tools and session tokens.
*   **Changes**:
    *   Move `create_debug_external_token` to a separate `test_utils.py` not included in production builds.
    *   Implement `SESSION_TOKEN_TTL` in `settings.py` (default to 1 hour).
*   **Testing**: Verify `create_debug_external_token` is inaccessible in the core engine; verify session tokens expire after the configured TTL.

### ✅DONE 26. Atomic JIT Player Registration
*   **Description**: Fix the race condition in `SecurityManager.verify_identity` where multiple simultaneous requests for a new player could cause duplicate or overwritten player records.
*   **Changes**:
    *   Update `SecurityManager.verify_identity` to use `db.create(..., fail_if_exists=True)`.
    *   Gracefully handle the "already exists" case by re-reading the existing record.
*   **Testing**: Simulate two concurrent identity verifications for the same new `player_id` and ensure only one DB create occurs without errors.

### ✅DONE 27. Scheduler Control (Cancellation Support)
*   **Description**: Prevent "orphan" update loops when sessions are re-initialized or terminated unexpectedly.
*   **Changes**:
    *   Add `cancel_update(session_id)` and `is_scheduled(session_id)` to `SchedulerInterface`.
    *   Implement these in `LocalScheduler` and ensure `PySlapEngine` uses them during cleanup or re-entry.
*   **Testing**: Schedule an update, cancel it, and verify the callback is never invoked.

### ✅DONE 28. Slot Recycling & Management
*   **Description**: Refactor slot assignment to support sparse slot maps and player departures.
*   **Changes**:
    *   Implement `leave_session` logic to vacate slots and allow priority-based recycling.
    *   Modify join logic in `PySlapEngine` to identify the first available slot using `get_slot_priority`.
    *   Fix matchmaking join race conditions and transaction handling.
*   **Testing**: Join 3 players, have the 2nd one leave, and verify the next player to join takes the 2nd slot.

### ✅DONE 29. Database Query Optimization
*   **Description**: Improve the performance of JSON-based queries to prevent full table scans as the database grows.
*   **Changes**:
    *   In `SQLiteDatabase`, implement indexing on frequently queried JSON paths (like `version` or `lobby_id`) using computed columns or partial indexes.
*   **Testing**: Performance benchmark of `query` and `update` operations with 100,000+ records.

---

## 🐛 Bug Fixes (Post-Audit of #29)

### ✅DONE 30. Fix Transaction Deadlock on Exception
*   **Description**: `start_transaction` acquires `self._lock` directly but `commit`/`rollback` are the only release sites. An exception thrown between `start_transaction` and either method leaves the lock permanently held, deadlocking all subsequent operations.
*   **Changes**:
    *   Introduce a `transaction()` context manager (`__enter__`/`__exit__`) on `SQLiteDatabase` that guarantees `rollback` (and lock release) on any exception.
    *   Replace bare `start_transaction` / `commit` / `rollback` call sites in the engine with `with db.transaction():`.
*   **Testing**: Raise an exception inside a transaction block and verify subsequent operations are not blocked.

### 31. Guard `_ensure_table_schema` on Read Paths
*   **Description**: `_build_filter_clauses` emits generated column names (e.g., `WHERE status = ?`) based on the hardcoded `_COLLECTION_SCHEMA`, but `_ensure_table_schema` is only called from `create`. On an existing database whose tables predate the optimization, any call to `query`, `update`, `conditional_update`, or `delete_by_filter` that filters on an optimized field will raise `OperationalError: no such column`.
*   **Changes**:
    *   Call `_ensure_table_schema` at the top of `query`, `update`, `conditional_update`, and `delete_by_filter` (guarded by `_table_exists` as already done), so generated columns and indexes are guaranteed to exist before any filter is applied.
*   **Testing**: Create a table manually (without generated columns), then call `query` with an optimized filter; verify it succeeds and the column is transparently added.

### 32. Fix Unhandled Error When Index Creation Follows Silent Column Failure
*   **Description**: In `_ensure_table_schema`, if `ALTER TABLE ADD COLUMN GENERATED ALWAYS AS` fails for any reason other than "duplicate column", the error is printed as a warning and execution continues. The subsequent `CREATE INDEX IF NOT EXISTS ... ON collection(field)` then references a non-existent column and raises an unhandled `OperationalError`.
*   **Changes**:
    *   Track which columns were successfully added (or already existed) in a local set inside `_ensure_table_schema`.
    *   Only create an index for a field if its column is confirmed to exist.
*   **Testing**: Simulate a column creation failure (e.g., mock `ALTER TABLE` to raise) and verify `_ensure_table_schema` completes without raising and that subsequent queries fall back to `json_extract`.

### 33. Chunk `__in` Batches to Respect SQLite Variable Limit
*   **Description**: `delete_by_filter` with `session_id__in` passes all expired session IDs as a single bind-parameter list. SQLite's `SQLITE_LIMIT_VARIABLE_NUMBER` is 999 on older versions (pre-3.32), causing a runtime crash when a cleanup pass exceeds that count.
*   **Changes**:
    *   In `_build_filter_clauses` (or in `delete_by_filter` before it calls the filter builder), split `__in` value lists into chunks of at most 999 and `UNION ALL` or loop the query/delete per chunk.
    *   Alternatively, enforce chunking at the call site in `PySlapEngine._cleanup_old_records` before passing `batch_ids`.
*   **Testing**: Run a cleanup with 2,000+ expired sessions and verify all related records are deleted without error.

### ✅DONE 34. Remove Duplicate `create` Method (Merge Artifact)
*   **Description**: `SQLiteDatabase` contains two `def create` definitions. The first (lines 73–83) is an incomplete leftover from a bad refactor; Python silently replaces it with the complete second definition. The orphaned code creates maintenance confusion and hides a misplaced block.
*   **Changes**:
    *   Delete the first (incomplete) `create` definition and the stray comment line that was left between it and `_COLLECTION_SCHEMA`.
*   **Testing**: All existing `create`-related tests pass without modification.

### 35. Cache Initialized Tables in `_ensure_table_schema`
*   **Description**: `_ensure_table_schema` is called on every `create` and (after fix #31) on every read path. It unconditionally executes `PRAGMA table_info` plus N `CREATE INDEX IF NOT EXISTS` DDL statements per call. Under insert load this is measurable overhead inside the global lock.
*   **Changes**:
    *   Add a `_initialized_tables: set[str]` instance field.
    *   At the top of `_ensure_table_schema`, return immediately if `collection` is already in the set.
    *   Add the collection to the set after all columns and indexes are confirmed.
*   **Testing**: Verify `PRAGMA table_info` is called at most once per collection per process lifetime under repeated inserts to the same collection.

### 36. Stream-Delete in `delete_by_filter` Instead of Loading All Rows
*   **Description**: `delete_by_filter` fetches all matching rows with `SELECT` before issuing `DELETE`, to return the deleted documents. For a cleanup of 100,000 expired sessions this loads all session JSON blobs into memory simultaneously. The engine only needs the IDs from the sessions result, not the full records.
*   **Changes**:
    *   Add an optional `return_ids_only: bool = False` parameter to `delete_by_filter`.
    *   When `True`, issue `SELECT record_id` instead of `SELECT data`, and return lightweight `[{"id": rid}]` dicts.
    *   Update `PySlapEngine._cleanup_old_records` to use `return_ids_only=True` when deleting sessions, since it only uses `s["id"]` from the result.
*   **Testing**: Run cleanup with 100,000+ expired sessions and verify peak memory does not scale with record count when `return_ids_only=True`.

