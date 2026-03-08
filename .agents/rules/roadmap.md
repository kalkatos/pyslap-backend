---
trigger: manual
---

# PySlap Roadmap & Technical Implementation Guide

This document provides technical blueprints for future PySlap enhancements. Refer to these items for subsequent development phases.

## **Important**: For any of these changes, no new entrypoint should be created, only if stricly necessary to avoid security risks or poor performance.

---

## ✨ Feature Improvements

### 1. Private Lobby System
*   **Description**: Add a lobby functionality to the matchmaking system. Allow players to create a private session identified by a user-friendly 6-character alphanumeric ID (e.g., "AB12CD") that can be shared with friends.
*   **Changes**:
    *   Update `Session` model to include a `lobby_id` field.
    *   Modify `PySlapEngine.create_session` to handle a `create_lobby` flag in `custom_data`.
    *   Implement logic to query sessions by `lobby_id` in the `DatabaseInterface`.
*   **Testing**: Start one client with `--create-lobby`, note the ID, then start a second client with `--join=ID`. Verify they join the same session.

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