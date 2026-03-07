---
trigger: always_on
---

# PySlap Roadmap & Technical Implementation Guide

This document provides technical blueprints for future PySlap enhancements. Refer to these items for subsequent development phases.

---

## 🛡️ Security Improvements

### 1. Stateless Session Tokens (JWT) - DONE ✅ -
*   **Description**: Replace random string tokens with signed JWTs to enable stateless verification of player and session identity without database lookups on every request.
*   **Modules**: `PyJWT` or `python-jose`.
*   **Changes**:
    *   `pyslap/core/security.py`: Update `generate_token` to create a signed JWT containing `player_id`, `session_id`, and `exp` (expiration).
    *   `local/app.py`: Implement a FastAPI dependency to extract and verify the JWT from the `Authorization: Bearer <token>` header.
*   **Testing**: Use `pytest` to verify that an expired token or a signature mismatch returns HTTP 401.

### 2. Action Sequencing (Nonces)
*   **Description**: Implement a `sequence_id` for actions to prevent replay attacks and ensure out-of-order network packets don't cause illegal state transitions.
*   **Changes**:
    *   `pyslap/models/domain.py`: Add `nonce: int` (or `sequence_id`) to the `Action` dataclass.
    *   `pyslap/core/engine.py`: Store `last_nonces: dict[player_id, int]` in the `GameState`.
    *   `pyslap/core/validator.py`: Add a check to ensure `incoming_nonce == last_nonce + 1`.
*   **Testing**: A client script sending two actions with the same nonce should see the second one rejected.

### 3. Role-Based Access Control (RBAC)
*   **Description**: Define explicit roles (PLAYER, SPECTATOR, ADMIN) and enforce permissions at the engine level (e.g., spectators can only call `get_state`).
*   **Changes**:
    *   `pyslap/models/domain.py`: Add `Role` enum (PLAYER, SPECTATOR, ADMIN).
    *   `pyslap/core/security.py`: Include the role in the verification record.
    *   `EntrypointInterface`: Add an `@ensure_role(Role.PLAYER)` decorator or check to `send_action`.
*   **Testing**: Register a player as a SPECTATOR and verify that `send_action` returns `False` or 403.

### 4. Rate Limiting
*   **Description**: Add rate-limiting middleware to protect the `/session` and `/action` endpoints from automated abuse or brute-force attempts.
*   **Modules**: `slowapi` or `fastapi-limiter`.
*   **Changes**:
    *   `local/app.py`: Register the Limiter middleware. Apply decorators like `@limiter.limit("5/minute")` to the `/session` endpoint.
*   **Testing**: Use a loop in `rps_client.py` to hit the endpoint rapidly and verify it receives HTTP 429.

---

## ✨ Feature Improvements

### 5. WebSocket Support (Real-time Pushes)
*   **Description**: Implement WebSockets to allow the server to push state updates directly to clients, reducing latency and removing the need for frequent polling.
*   **Modules**: `fastapi.WebSockets`.
*   **Changes**:
    *   `local/app.py`: Add a `@app.websocket("/ws/{session_id}/{player_id}/{token}")` endpoint.
    *   `local/local_scheduler.py`: Implement an observer pattern where the scheduler notifies WebSocket handlers when an update loop tick completes.
*   **Testing**: Open two browser tabs or scripts and verify state updates appear instantly without `GET /state` polling.

### 6. Matchmaking Lobby
*   **Description**: Create a queuing system where players can wait for opponents; the server auto-starts sessions when enough players are matched.
*   **Changes**:
    *   `pyslap/core/matchmaker.py` (New): A service that holds a queue of `(player_id, game_id)`.
    *   `local/app.py`: Add `/matchmake/join` and `/matchmake/status` endpoints.
*   **Testing**: Run two client instances simultaneously; verify they both receive the same `session_id` after a few seconds.

### 7. Persisted Stats & Leaderboards
*   **Description**: Track win/loss records across sessions and provide endpoints for global or game-specific leaderboards.
*   **Changes**:
    *   `pyslap/core/engine.py`: On `SessionStatus.FINISHED`, trigger a `db.create("statistics", ...)` call.
    *   `local/app.py`: Add a `/leaderboard/{game_id}` endpoint that queries the DB.
*   **Testing**: Play 3 rounds of RPS, then query the leaderboard to verify win/loss counts are updated.

### 8. Match Replay System
*   **Description**: Store a complete history of all actions in a session to allow "time-travel" debugging or post-match playback for players.
*   **Changes**:
    *   `pyslap/core/engine.py`: Log every accepted action into a `match_history` collection.
    *   `local/app.py`: Add `/replay/{session_id}/{tick}` to reconstruct the state at a specific point.
*   **Testing**: Use a script to fetch a finished match and verify you can "watch" the sequence of moves round-by-round.

### 9. Standardized AI Plugin System
*   **Description**: Refactor bot logic into an `AiInterface` (e.g., `RandomAi`, `MinimaxAi`, `LlmAi`) that can be optionally attached to any game via session customization.
*   **Changes**:
    *   `pyslap/core/ai_bot.py` (New): Define an abstract `AiProvider` with a `get_move(state)` method.
    *   Refactor `games/rps.py`: Move the random choice logic out into a `RandomRpsAi` class.
*   **Testing**: Pass `{"bot_difficulty": "expert"}` in `custom_data` and verify the engine swaps the AI logic accordingly.

### 10. Spectator Mode
*   **Description**: Allow users to join existing sessions with a restricted view-only token that hides private state data.
*   **Changes**:
    *   `pyslap/core/security.py`: Allow generating tokens with a `scope="read_only"` claim.
    *   `local/local_entrypoint.py`: In `get_state`, if the token is read-only, force `private_state` to be empty.
*   **Testing**: Connect a third client to an ongoing match and verify they see public scores but not the hidden choices of other players.
