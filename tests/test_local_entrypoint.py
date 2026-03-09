import asyncio
import os
import pytest
from typing import Dict
from local.sql_database import SQLiteDatabase
from local.local_scheduler import LocalScheduler
from local.local_entrypoint import LocalEntrypoint
from pyslap.core.engine import PySlapEngine
from games.rps import RpsGameRules

import uuid

@pytest.fixture
def setup_engine():
    db_path = f"temp_database_{uuid.uuid4().hex}"
    
    db = SQLiteDatabase(db_path)
    # RpsGameRules needs to be initialized. 
    # Based on pyslap/core/engine.py, it expects a dict of games_registry
    games = {"rps": RpsGameRules()}
    
    from unittest.mock import MagicMock
    scheduler = MagicMock()
    engine = PySlapEngine(db, scheduler, games)
    entrypoint = LocalEntrypoint(engine)
    
    # Create a game config for rps
    db.create("game_configs", {
        "id": "rps",
        "update_interval_ms": 500,
        "max_lifetime_sec": 3600,
        "session_timeout_sec": 600
    })
    
    yield entrypoint, engine, db
    
    db.dispose()

def test_local_entrypoint_flow(setup_engine):
    entrypoint, engine, db = setup_engine
    
    # 1. Create a session via engine (entrypoint doesn't have create_session in interface yet?)
    # Wait, PySlapEngine has create_session. EntrypointInterface doesn't.
    # Usually the entrypoint would have a way to start things or we use the engine directly for setup.
    
    player_id = "player1"
    player_name = "Alex"
    
    # Mocking security verify_identity if needed, but PySlapEngine.create_session calls it.
    # PySlapEngine.security uses db.
    db.create("players", {"id": player_id, "name": player_name, "token": "secret_token"})
    
    auth_token = engine.security.create_debug_external_token(player_id, player_name)
    session_info = engine.create_session("rps", auth_token)
    assert session_info is not None
    session_id = session_info["session_id"]
    token = session_info["token"]
    
    # 2. Get state via entrypoint
    state = entrypoint.get_state(session_id, player_id, token)
    assert state is not None
    # Rps initial state has round 1
    # Note: RpsGameRules.apply_update_tick initializes public_state on first tick.
    # PySlapEngine.create_session calls scheduler.schedule_next_update.
    # We might need to wait for the first tick or trigger it.
    
    # Force an update tick to initialize state
    engine.process_update_loop(session_id)
    
    state = entrypoint.get_state(session_id, player_id, token)
    assert state.public_state["round"] == 1
    assert state.public_state["phase"] == "waiting_for_move"
    
    # 3. Send action via entrypoint
    entrypoint.send_action(session_id, player_id, token, "move", {"choice": "R"}, 1)
    
    # 4. Check if action is logged in DB
    actions = db.query("actions", {"session_id": session_id})
    assert len(actions) == 1
    assert actions[0]["action_type"] == "move"
    assert actions[0]["payload"]["choice"] == "R"
    
    # 5. Get data via entrypoint
    action_data = entrypoint.get_data(session_id, player_id, token, "actions", {})
    assert len(action_data) == 1
    assert action_data[0]["action_type"] == "move"

def test_local_entrypoint_registers_ack(setup_engine):
    entrypoint, engine, db = setup_engine
    
    player_id = "player1"
    player_name = "Alex"
    db.create("players", {"id": player_id, "name": player_name, "token": "secret_token"})
    auth_token = engine.security.create_debug_external_token(player_id, player_name)
    session_info = engine.create_session("rps", auth_token)
    session_id = session_info["session_id"]
    token = session_info["token"]
    
    # Manually transition state to a gated phase ("round_complete" for RPS)
    state_data = db.read("states", session_id)
    state_data["public_state"]["phase"] = "round_complete"
    state_data["phase_ack"] = {player_id: False}
    db.update("states", session_id, state_data)
    
    # 1. Fetch state - this should trigger the ack registration
    state = entrypoint.get_state(session_id, player_id, token)
    
    # 2. Verify state returned has the phase
    assert state.public_state["phase"] == "round_complete"
    
    # 3. Verify DB was updated with ack
    updated_state_data = db.read("states", session_id)
    assert updated_state_data["phase_ack"][player_id] is True

if __name__ == "__main__":
    # Manual run if needed
    pass
