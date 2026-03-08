# PySlap Framework

PySlap is a framework designed to build scalable, serverless-friendly, and stateless multiplayer games using Python. This document explains how to use the internal framework modules provided in the `pyslap` directory.

## Core Concepts

The framework separates the game orchestration (engine) from the specific game logic and infrastructure implementations (interfaces). This separation allows you to run different games on the same engine and deploy on various platforms.

The main modules in `pyslap` are categorized into three areas:
- **`models/`**: Domain objects.
- **`interfaces/`**: Abstract classes defining infrastructure requirements.
- **`core/`**: The core framework logic and engine.

---

## 1. Domain Models (`pyslap/models/domain.py`)

All interactions in PySlap use typed data classes to ensure a strict data contract.
- **`Player`**: Represents a user in the system (`player_id`, `name`, `role`, `token`).
- **`Action`**: Actions sent by a player to update the game state (`action_type`, `payload`, `timestamp`, `nonce`).
- **`GameState`**: The central object holding the current state. Contains `public_state` (shared among all) and `private_state` (specific configuration/data per `player_id`).
- **`Session`**: Tracks the metadata of an active game, including `status`, `players`, and timing parameters.
- **`GameConfig`**: Dictates rules like `update_interval_ms`, `max_lifetime_sec`, and custom settings for a specific game implementation.

---

## 2. Implementing Game Logic (`pyslap/core/game_rules.py`)

To implement a new game using the framework, you must inherit from `GameRules` inside `pyslap/core/game_rules.py` and implement its abstract methods:

1. **`create_game_state(self, players, custom_data)`**: Initialize your game state variables. Prepare any private/public state attributes.
2. **`setup_player_state(self, state, player)`**: Initialize private state variables for a dynamically joining player.
3. **`validate_action(self, action, state)`**: Return `True` if a player's action is currently legal.
4. **`apply_action(self, action, state)`**: Modify the `GameState` primarily via state variables reflecting the validated action. 
5. **`apply_update_tick(self, state, delta_ms)`**: Handle periodic game updates (e.g., automated timeouts, physics steps) unaffected by direct player actions.
6. **`check_game_over(self, state)`**: Return `True` when the match has ended.
7. **`get_phase_gates(self)`** *(Optional)*: Define specific game phases that require all players to acknowledge before proceeding.

---

## 3. Creating Infrastructure Interfaces (`pyslap/interfaces/`)

Since PySlap is designed to be serverless and infrastructure-agnostic, you must provide concrete implementations for the framework's interfaces:

### `DatabaseInterface` (`pyslap/interfaces/database.py`)
Provides strict CRUD capabilities to persist `GameConfigs`, `Sessions`, `GameStates`, and `Actions`. It uses operations such as `create()`, `read()`, `update()`, `delete()`, and `query()`.

### `SchedulerInterface` (`pyslap/interfaces/scheduler.py`)
Handles scheduling the primary loop. The engine calls `schedule_next_update(session_id, delay_ms)` to delay its next processing cycle (ideal for polling networks, EventBridge, or async event loops).

### `EntrypointInterface` (`pyslap/interfaces/entrypoint.py`)
Defines the outward-facing contract to accept player data. Contains specifications for `start_session`, `send_action`, `get_state`, and `get_data`. You can map these to local Python calls, AWS Lambda functions, WebSockets, or FastAPI endpoints.

---

## 4. The Engine Orchestrator (`pyslap/core/engine.py`)

The `PySlapEngine` ties it all together. It handles stateless validation, orchestration of the scheduler loop, and database syncing.

To use the engine:
1. Initialize your Database and Scheduler interface implementations.
2. Map your `GameRules` subclass instances into a dictionary (registry).
3. Instantiate `PySlapEngine(db, scheduler, games_registry)`.

The engine automatically cleans up stale connections via `_cleanup_old_records()`. It interacts securely by leveraging the inner `SecurityManager` (`pyslap/core/security.py`) to gate valid requests via tokens, while the `Validator` (`pyslap/core/validator.py`) restricts inputs through strict rate limiting, lifetime timeouts, and nonce mismatch checks.

**Key workflow inside the Engine**:
- **`create_session`**: Verifies identities, provisions state, sets tokens, and initiates the first `scheduler` hook.
- **`register_action`**: Used by the entrypoint to pipe in player actions. Applies security checking and logs against the database for the active loop.
- **`process_update_loop`**: The heartbeat execution invoked by the scheduler. Loads state, clears timed-out sessions, fires `apply_update_tick` and un-processed `apply_action` logic, and reschedules the upcoming tick.
