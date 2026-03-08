---
trigger: manual
---

# PySlap Roadmap & Technical Implementation Guide

This document provides technical blueprints for future PySlap enhancements. Refer to these items for subsequent development phases.

---

## 🛡️ Security Improvements

### 1. ✅DONE Stateless Session Tokens (JWT)
*   **Description**: Replace random string tokens with signed JWTs to enable stateless verification of player and session identity without database lookups on every request.
*   **Modules**: `PyJWT` or `python-jose`.
*   **Changes**:
    *   `pyslap/core/security.py`: Update `generate_token` to create a signed JWT containing `player_id`, `session_id`, and `exp` (expiration).
    *   `local/app.py`: Implement a FastAPI dependency to extract and verify the JWT from the `Authorization: Bearer <token>` header.
*   **Testing**: Use `pytest` to verify that an expired token or a signature mismatch returns HTTP 401.

### 2. ✅DONE Action Sequencing (Nonces)
*   **Description**: Implement a `sequence_id` for actions to prevent replay attacks and ensure out-of-order network packets don't cause illegal state transitions.
*   **Changes**:
    *   `pyslap/models/domain.py`: Add `nonce: int` (or `sequence_id`) to the `Action` dataclass.
    *   `pyslap/core/engine.py`: Store `last_nonces: dict[player_id, int]` in the `GameState`.
    *   `pyslap/core/validator.py`: Add a check to ensure `incoming_nonce == last_nonce + 1`.
*   **Testing**: A client script sending two actions with the same nonce should see the second one rejected.

### 3. ✅DONE Role-Based Access Control (RBAC)
*   **Description**: Define explicit roles (PLAYER, SPECTATOR, ADMIN) and enforce permissions at the engine level (e.g., spectators can only call `get_state`).
*   **Changes**:
    *   `pyslap/models/domain.py`: Add `Role` enum (PLAYER, SPECTATOR, ADMIN).
    *   `pyslap/core/security.py`: Include the role in the verification record.
    *   `EntrypointInterface`: Add an `@ensure_role(Role.PLAYER)` decorator or check to `send_action`.
*   **Testing**: Register a player as a SPECTATOR and verify that `send_action` returns `False` or 403.

### 4. ✅DONE Rate Limiting
*   **Description**: Add rate-limiting middleware to protect the `/session` and `/action` endpoints from automated abuse or brute-force attempts.
*   **Modules**: `slowapi` or `fastapi-limiter`.
*   **Changes**:
    *   `local/app.py`: Register the Limiter middleware. Apply decorators like `@limiter.limit("5/minute")` to the `/session` endpoint.
*   **Testing**: Use a loop in `rps_client.py` to hit the endpoint rapidly and verify it receives HTTP 429.

---

## ✨ Feature Improvements

### 5. ✅DONE Matchmaking Lobby
*   **Description**: Create a queuing system where players can wait for opponents; the server auto-starts sessions when enough players are matched.
*   **Changes**:
    *   `pyslap/core/matchmaker.py` (New): A service that holds a queue of `(player_id, game_id)`.
    *   `local/app.py`: Add `/matchmake/join` and `/matchmake/status` endpoints.
*   **Testing**: Run two client instances simultaneously; verify they both receive the same `session_id` after a few seconds.
