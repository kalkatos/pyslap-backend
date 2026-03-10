---
trigger: manual
---

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
### 1. The "Joiner" Phase Paradox
*   **Description**: Sessions can get stuck in "waiting_for_players" if the joiner doesn't trigger a tick.
*   **Fix**: Ensure `setup_player_state` advances the game phase and increments the state version when player requirements are met.

### 2. Deterministic Player Roles
*   **Description**: Relying on dictionary key order to determine Player 1 vs Player 2 is unstable across systems.
*   **Fix**: Explicitly store `p1_id`, `p2_id` (etc.) in the `public_state` when a match begins.

### 3. Partial State Updates
*   **Description**: Overwriting the entire `private_state` for a player erases other persistent data like scores.
*   **Fix**: Always update specific keys within the player states instead of replacing the dictionary.

### 4. Gated Phase Management
*   **Description**: Gated phases can block game progress if players don't acknowledge the transition.
*   **Fix**: Implement an explicit `ack` action and automate it in the client implementation.

### 5. Serverless Determinism
*   **Description**: Unseeded randomness can cause divergent states if a tick is retried by the provider.
*   **Fix**: Store random seeds in the `GameState` and use `random.Random(seed)` for all game-critical logic.

### 6. Frame-Rate Independence
*   **Description**: Assuming a fixed 500ms interval for logic cycles leads to jittery or incorrect timing (e.g. cooldowns).
*   **Fix**: Always use the `delta_ms` parameter in `apply_update_tick` for time-based calculations.
