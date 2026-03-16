# PySlap Roadmap & Technical Implementation Guide

This document provides technical blueprints for future PySlap enhancements. Refer to these items for subsequent development phases.

## **Important**: For any of these changes, no new entrypoint should be created, only if stricly necessary to avoid security risks or poor performance.

Features already done are marked with ✅DONE

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

### 25. Security Hardening
*   **Description**: Reduce the exploit surface of debugging tools and session tokens.
*   **Changes**:
    *   Move `create_debug_external_token` to a separate `test_utils.py` not included in production builds.
    *   Implement `SESSION_TOKEN_TTL` in `settings.py` (default to 1 hour).
*   **Testing**: Verify `create_debug_external_token` is inaccessible in the core engine; verify session tokens expire after the configured TTL.

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


