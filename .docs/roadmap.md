# PySlap Roadmap & Technical Implementation Guide

This document provides technical blueprints for future PySlap enhancements. Refer to these items for subsequent development phases.

## **Important**: For any of these changes, no new entrypoint should be created, only if stricly necessary to avoid security risks or poor performance.

Features already done are marked with ✅DONE

---

## ✨ Feature Improvements

### ✅DONE 1. Private Lobby System
*   **Description**: Add a lobby functionality to the matchmaking system. Allow players to create a private session identified by a user-friendly 6-letter ID (e.g., "QOEMDU") that can be shared with friends.
*   **Changes**:
    *   Update `Session` model to include a `lobby_id` field.
    *   Modify `PySlapEngine.create_session` to handle a `create_lobby` flag in `custom_data`.
    *   Implement logic to query sessions by `lobby_id` in the `DatabaseInterface`.
*   **Testing**: Start one client with `--create-lobby`, note the ID, then start a second client with `--join <ID>`. Verify they join the same session.

### 2. Spectator Mode
*   **Description**: Support users watching matches without participating.
*   **Changes**:
    *   Update `PySlapEngine.register_action` to allow joining sessions beyond the `max_players` limit if the role is `SPECTATOR`.
    *   Update `GameRules.to_player_state` to ensure spectators receive the full public state but no private data.
*   **Testing**: Join a match with 2 players and 1 spectator. Verify the spectator sees updates but cannot move.

### 3. Match Replay & History
*   **Description**: Record the sequence of actions and state transitions to allow post-game review.
*   **Changes**:
    *   Add an `action_history` collection to the database.
    *   Update the engine to archive the full state and action logs when a session terminates.
*   **Testing**: Play a full match, then use a script to fetch the history and verify every move is logged in order.

### 4. Global Leaderboards
*   **Description**: Track player wins and losses across all sessions and games.
*   **Changes**:
    *   Implement a `player_stats` collection in the database.
    *   Update the engine to report winners to the database when a game ends.
*   **Testing**: Play multiple matches as the same player and verify the win count increments in the DB.

### 5. In-Game Chat System
*   **Description**: Simple text communication between players during active sessions.
*   **Changes**:
    *   Add a `chat` action type to the engine.
    *   Store messages in a `messages` list within the `public_state` for real-time syncing.
*   **Testing**: Send a chat action from one client and verify it appears in the display of the other client.

## Fixes
### ✅DONE 6. The "Joiner" Phase Paradox
*   **Description**: Sessions can get stuck in "waiting_for_players" if the joiner doesn't trigger a tick.
*   **Definitive Fix**: The `PySlapEngine` must automatically trigger a state update and version bump as soon as a session transitions from `MATCHMAKING` to `ACTIVE`, ensuring the game starts immediately without waiting for the next periodic tick. (update rps.py accordingly)

### ✅DONE 7. Sticky Slot Assignment
*   **Description**: Relying on dictionary key order or dynamic list indices is brittle, as player positions shift if someone leaves or disconnects.
*   **Definitive Fix**: The framework must implement a **Sticky Slot** system. When a player joins, they are assigned a permanent slot identifier (e.g., `slot_0`, `slot_1`) stored in a dedicated mapping (e.g., `GameState.slots`) and persisted in the DB. This assignment is immutable for the duration of the session; if a player leaves, their slot remains reserved or empty, ensuring other players' references never shift. (update rps.py accordingly)

### ✅DONE 8. State Update Integrity
*   **Description**: Overwriting the entire `private_state` for a player erases other persistent data like scores.
*   **Definitive Fix**: Implement a protected state mutation interface in the Engine that enforces partial updates to `private_state` and `public_state`, preventing game logic from accidentally nullifying or overwriting existing persistent data like scores. (update rps.py accordingly)

### ✅DONE 9. Native Gated Transitions
*   **Description**: Gated phases can block game progress if players don't acknowledge the transition.
*   **Definitive Fix**: Build the `ack` (acknowledgment) mechanism directly into the `PySlapEngine` as a core framework action. This allows any game to define gated phases that the Engine manages automatically, without requiring custom "ack" logic in every game. (update rps.py accordingly)

### ✅DONE 10. Managed Determinism
*   **Description**: Unseeded randomness can cause divergent states if a tick is retried by the provider.
*   **Definitive Fix**: The Engine must manage a `random_seed` within the `GameState` and provide a pre-seeded, deterministic random generator to the `GameRules` to ensure execution is consistent across serverless retries. (update rps.py accordingly)

### 11. Real-Time Delta Enforcement
*   **Description**: Assuming a fixed 500ms interval for logic cycles leads to jittery or incorrect timing (e.g. cooldowns).
*   **Definitive Fix**: The Engine must handle the precise calculation of `delta_ms` based on actual database timestamps, ensuring that `GameRules` receive accurate time-step information regardless of external scheduling delays or serverless cold starts. (update rps.py accordingly)

### 12. Update README.md
*   **Description**: Check if @pyslap\README.md is up to date with current codebase workflow, and update if necessary.

## 🛠️ Audit-Driven Fixes (High Priority)

### 13. Atomic Matchmaking
*   **Description**: Prevent players from overwriting each other when joining a session simultaneously.
*   **Changes**: Implement atomic "Compare-And-Swap" logic in `engine.create_session` to ensure player slots are filled correctly without race conditions.

### 14. Distributed Update Loop Protection
*   **Description**: Ensure exactly one loop instance runs per session in serverless environments to prevent "Last Write Wins" data loss.
*   **Changes**: Implement a distributed locking or lease pattern in `process_update_loop` using atomic database operations.

### 15. Decoupled Data Cleanup
*   **Description**: Stop scanning the entire database for old records on every request instantiation.
*   **Changes**: Move `_cleanup_old_records` from `PySlapEngine.__init__` to a dedicated maintenance task or background worker.

### 16. Server-Side Query Filtering
*   **Description**: Prevent loading entire collections into memory for filtering.
*   **Changes**: Update `DatabaseInterface.query` to support efficient database-level filtering (e.g., SQL `WHERE` clauses).

### 17. Functional Anti-Spam
*   **Description**: Replace the current `True` stub with actual rate-limiting logic.
*   **Changes**: Implement tracking of action frequency per player in `Validator.validate_action_rate`.

### 18. Deterministic Lobby Generation
*   **Description**: Ensure lobby ID generation is idempotent and testable.
*   **Changes**: replace global `random.choice` with a seeded local generator derived from requester inputs.

### 19. Granular State Versioning
*   **Description**: Ensure clients detect every change to the game state.
*   **Changes**: Bump `state_version` on every state-mutating action or internal tick update, not just on phase transitions.


