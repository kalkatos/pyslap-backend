# Technical Analysis: Single-Instance Update Loop Enforcement

The objective is to ensure that for any given game session, exactly one instance of the `process_update_loop` is running at any time, preventing concurrent race conditions and "last write wins" data loss.

## 1. Feasibility Analysis

In a serverless environment (Lambda/Cloud Functions), enforcing a singleton per session is **highly feasible** but requires a shared coordination layer (the database).

### Implementation Strategy: The "Lease" Pattern
1.  **Lock Acquisition**: When `process_update_loop(session_id)` starts, it attempts to "acquire a lease" for the session in the DB.
2.  **Conditional Update**: This must be an atomic operation. E.g., `UPDATE sessions SET loop_locked_until = <now + 10s> WHERE id = <session_id> AND (loop_locked_until < <now> OR loop_locked_until IS NULL)`.
3.  **Execution**: If the update affects 1 row, progress. Otherwise, exit immediately (another loop is active).
4.  **Release**: Upon completion, clear the lock.

### Current Environment Constraints
The current `DatabaseInterface` lacks an atomic conditional update/locking method. Implementing this would require adding a `conditional_update` or `acquire_lock` method to the interface.

---

## 2. Pros (The Case for Singleton)

*   **Strict Serializability**: Guaranteed that game logic is never applied to stale data. No need for complex client-side conflict resolution.
*   **Predictable RNG**: Deterministic seeds (`GameState.random_seed`) work perfectly because the sequence is never "forked" by parallel executions.
*   **Simplified Game Rules**: Developers writing `GameRules` don't need to worry about concurrency; they can trust that `apply_update_tick` is the sole modifier of the state.
*   **Reduced DB Load**: Prevents "thundering herd" issues where multiple scheduled tasks or client polls trigger redundant heavy logic.

---

## 3. Cons (The Risks)

*   **The "Hanging Lock" Problem**: If a serverless instance crashes during execution (e.g., OOM or timeout), the lock remains set. The next loop must wait for the lease to expire (typically several seconds), causing a perceived "hang" in the game.
*   **Increased Latency**: Every tick now requires an extra round-trip to the DB for the lock, adding 20-100ms per cycle.
*   **Complexity of Expiration**: Ticks are scheduled every 500ms. If a lock expires in 10s, but a tick takes 12s, you still get a race. The lock must be "heartbeated" or the timeout must be very carefully tuned.
*   **Scalability Ceiling**: It limits the system to one logical thread per match. (Though for games like RPS/Chess, this is more than enough).

---

## 4. Comparison with OCC (Optimistic Concurrency Control)

| Feature | Singleton Loop Enforcement | Optimistic Concurrency (OCC) |
| :--- | :--- | :--- |
| **Philosophy** | "Pessimistic" - Stop trouble before it starts. | "Optimistic" - Detect trouble and retry. |
| **Complexity** | High (requires distributed locking/leases). | Medium (requires version checks on save). |
| **Overhead** | Adds latency to *every* tick. | Only adds latency on *conflicts* (retries). |
| **Best For** | Real-time, continuous physics/Logic. | Turn-based, low-frequency actions. |

---

## 5. Recommendation

For **PySlap**, given its **polling model (>= 500ms)** and **stateless serverless target**:

**A Hybrid Approach is best:**
1.  Use **Leases** on the scheduler side to prevent duplicate "ghost" ticks.
2.  Use **OCC (Version Bumping)** on the database side as a "final safety net" to ensure that if a lock fails, data is still not corrupted.

Ensuring a single loop start is **desirable** for game feel (consistency), but **OCC is mandatory** for data integrity.
