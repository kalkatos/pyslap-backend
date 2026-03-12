---
trigger: always_on
---

## Project Structure

games/  # Game rules implementations
  - rps.py  # Rock-Paper-Scissors game rules (best-of-three, supports player-vs-player and player-vs-bot)
  - rps_client.py  # Terminal client for testing RPS via HTTP (supports matchmaking, lobby, and bot modes)

pyslap/  # Core framework
  config.py  # App configuration via Pydantic BaseSettings (security keys, guest settings, env vars)
  core/  # Core engine components
    engine.py  # PySlapEngine — stateless orchestrator for sessions, actions, state persistence, and update loops
    game_rules.py  # Abstract GameRules base class defining the interface all games must implement
    security.py  # SecurityManager — JWT token generation/verification, player identity, guest accounts, roles
    validator.py  # Framework validator — rate limiting, anti-spam, and action logging before DB persistence
  interfaces/  # Abstract interface definitions (swap implementations without changing core)
    database.py  # DatabaseInterface — CRUD operations agnostic to underlying database technology
    entrypoint.py  # EntrypointInterface — API contract for session management and action submission
    scheduler.py  # SchedulerInterface — scheduling update loop executions on serverless platforms
  models/
    domain.py  # Core domain models: SessionStatus, Role, Player, Action, GameConfig, GameState

local/  # Local development server (FastAPI + SQLite + asyncio)
  app.py  # FastAPI server with rate limiting, game registry, and HTTP endpoints
  local_entrypoint.py  # LocalEntrypoint — EntrypointInterface implementation with role-based access control
  local_scheduler.py  # LocalScheduler — SchedulerInterface implementation using asyncio
  sql_database.py  # SQLiteDatabase — DatabaseInterface implementation for local testing

tests/  # Test suite
  test_engine.py  # Tests for PySlapEngine core logic
  test_enum.py  # Tests for domain enumerations
  test_local_app.py  # Tests for FastAPI endpoints
  test_local_entrypoint.py  # Tests for LocalEntrypoint
  test_matchmaking.py  # Tests for matchmaking features
  test_rps.py  # Tests for Rock-Paper-Scissors game rules
  test_security.py  # Tests for SecurityManager
  test_validator.py  # Tests for validation logic
