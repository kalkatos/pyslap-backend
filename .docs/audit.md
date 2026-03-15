# PySlap Backend Audit Report

## 1. Executive Summary

This audit evaluates the PySlap backend framework for production readiness. While the architecture is modular and follows serverless principles (statelessness, interface-driven design), several **critical race conditions** and **performance bottlenecks** were identified that could lead to data corruption, duplicate execution, or systemic instability in high-concurrency environments.

---

## 2. Concurrency and Race Conditions

### 2.1. Distributed Loop Lock Create-Race
- **File**: `pyslap/core/engine.py:380-383`
- **Issue**: The `_try_acquire_loop_lock` method attempts to create a lock record if it doesn't exist. However, the `DatabaseInterface.create` method (as implemented in `SQLiteDatabase`) uses `INSERT OR REPLACE`. 
- **Impact**: Two different serverless instances could simultaneously "create" the lock, both succeeding. This leads to **duplicate update loop execution** for the same session, potentially corrupting game state via interleaved updates.
- **Severity**: **CRITICAL**

### 2.2. Non-Atomic Rate Limiting
- **File**: `pyslap/core/validator.py:28-54`
- **Issue**: Rate limiting follows a "Read -> Check -> Write" pattern across two separate methods (`validate_action_rate` and `record_action_rate`).
- **Impact**: In a distributed environment, a user can send multiple actions simultaneously. Multiple instances might read the same "last_action_at" timestamp, pass the check, and allow all actions through.
- **Severity**: **HIGH**

### 2.3. JIT Player Registration Race
- **File**: `pyslap/core/security.py:62-71`
- **Issue**: `verify_identity` performs JIT registration. If a new player joins multiple sessions at once, multiple calls to `db.create("players", ...)` will occur. 
- **Impact**: Depending on the DB implementation, this causes primary key violations or duplicate records. 
- **Severity**: **MEDIUM**

### 2.4. Matchmaking State Overwrite
- **File**: `pyslap/core/engine.py:157-180`
- **Issue**: While the `sessions` update uses CAS (`expected_version`), the subsequent `states` update does not.
- **Impact**: If two players join a matchmaking session in extremely close proximity, the session logic might correctly sequence them, but their state mutations (e.g., slot assignments) might overwrite each other if the `states` update doesn't enforce versioning.
- **Severity**: **HIGH**

---

## 3. Performance and Bottlenecks

### 3.1. Matchmaking "Thundering Herd"
- **File**: `pyslap/core/engine.py:119-183`
- **Issue**: The CAS retry loop in matchmaking query all waiting sessions and tries to join the first available one.
- **Impact**: In a high-traffic scenario where 100 players want to join 1 available lobby, all 100 will query the DB, and only 1 will succeed. The other 99 will retry, repeating the query. This causes exponential database load.
- **Severity**: **HIGH**

### 3.2. Sequential Cleanup
- **File**: `pyslap/core/engine.py:57-88`
- **Issue**: `cleanup_old_records` iterates through sessions one by one to delete related actions and rate limits.
- **Impact**: If cleaning up thousands of sessions, this becomes a massive, slow foreground task. It should be refactored into a single batch delete or backgrounded.
- **Severity**: **MEDIUM**

### 3.3. JSON Extraction Performance
- **File**: `local/sql_database.py:102, 131`
- **Issue**: Queries and CAS checks rely on `json_extract`.
- **Impact**: Without computed columns or indexes on these JSON paths, every version check or filtered query requires a full table scan.
- **Severity**: **LOW** (Local Dev) / **HIGH** (If mirrored in production DB like Postgres/NoSQL without proper indexing)

---

## 4. Architectural Smells

### 4.1. Lack of Cross-Record Transactions
- **Observation**: The engine frequently updates multiple records (Session + State) across different collections. 
- **Problem**: There is no transaction interface. If the second update fails, the system is left in a partially updated state.

### 4.2. Scheduler Orphanage
- **Observation**: `SchedulerInterface` has no `cancel` or `is_scheduled` methods.
- **Problem**: If a session is recreated or re-initialized, multiple update loops can be scheduled for the same `session_id`.

### 4.3. Sticky Slot Fragmentation
- **Observation**: Slots are assigned as `slot_0`, `slot_1`, etc.
- **Problem**: If a game supports 10 players and player 0 leaves, `slot_0` remains tied to that ID. If a new player joins, the engine always appends (`slot_len`). This can lead to sparse slot maps unless the specific GameRules implementation handles slot recycling (which `RpsGameRules` does not fully do).

---

## 5. Security Findings

### 5.1. Debug Token Exposure
- **File**: `pyslap/core/security.py:83-90`
- **Issue**: `create_debug_external_token` is part of the core `SecurityManager`.
- **Recommendation**: Move to a testing utility or wrap in `if settings.debug:`.

### 5.2. Token TTL
- **Issue**: Session tokens are valid for 24 hours. For a polling-based real-time game, this is excessively long and increases the blast radius of a leaked token.

---

## 6. Recommendations

1.  **Atomic Lock Creation**: Update `DatabaseInterface.create` to support a `fail_if_exists` flag, and use it in `_try_acquire_loop_lock`.
2.  **Transaction Support**: Introduce a `transaction` or `batch_update` method to the `DatabaseInterface` to ensure Session and State updates are atomic.
3.  **Refined Matchmaking**: Use a "claimed" status or a separate matchmaking queue to prevent the CAS thundering herd on active sessions.
4.  **Batch Deletes**: Refactor `cleanup_old_records` to use a single `DELETE FROM ... JOIN` or equivalent batch operation.
5.  **Rate Limit Atomicity**: Move rate limiting to a database-level increment or a "last_action" check within the same atomic update as the action log.
