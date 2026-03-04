import time
from typing import Any, Dict
from unittest.mock import MagicMock

from pyslap.core.engine import PySlapEngine
from pyslap.core.game_rules import GameRules
from pyslap.models.domain import Action, GameState, SessionStatus


# --- Dummy Game Rules for Testing ---
class DummyGame(GameRules):
    def validate_action(self, action: Action, state: GameState) -> bool:
        return action.action_type == "valid_move"

    def apply_action(self, action: Action, state: GameState) -> GameState:
        state.public_state["last_move"] = action.payload
        return state

    def apply_update_tick(self, state: GameState, delta_ms: int) -> GameState:
        state.public_state["ticks"] = state.public_state.get("ticks", 0) + 1
        return state

    def check_game_over(self, state: GameState) -> bool:
        return state.public_state.get("ticks", 0) > 10

    def prepare_state(self, state: GameState, player_id: str, recent_actions: list) -> Dict[str, Any]:
        return {"public": state.public_state, "private": {}}


# --- Test Cases ---
def test_engine_create_session():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    
    # Mock DB read for GameConfig
    mock_db.read.return_value = {"update_interval_ms": 1000}
    
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    
    result = engine.create_session("dummy", "p1", "Alice")
    
    assert result is not None
    assert "session_id" in result
    assert "token" in result
    assert "state" in result
    
    # Verify DB calls
    assert mock_db.create.call_count == 2 # Session and State
    args1, kwargs1 = mock_db.create.call_args_list[0]
    args2, kwargs2 = mock_db.create.call_args_list[1]
    
    assert args1[0] == "sessions"
    assert args2[0] == "states"
    
    # Verify Scheduler Call
    mock_scheduler.schedule_next_update.assert_called_once_with(result["session_id"], 1000)


def test_engine_create_session_unknown_game():
    engine = PySlapEngine(db=MagicMock(), scheduler=MagicMock(), games_registry={})
    result = engine.create_session("unknown", "p1", "Alice")
    assert result is None


def test_engine_register_action_success():
    mock_db = MagicMock()
    engine = PySlapEngine(db=mock_db, scheduler=MagicMock(), games_registry={})
    
    # Mock session fetch
    current_time = time.time()
    mock_db.read.return_value = {
        "session_id": "sid_1",
        "game_id": "dummy",
        "status": SessionStatus.ACTIVE,
        "players": {},
        "created_at": current_time,
        "last_action_at": current_time - 1000
    }
    
    result = engine.register_action(
        session_id="sid_1", 
        player_id="p1", 
        token="valid-token", 
        action_type="move", 
        payload={"x": 5}
    )
    
    assert result is True
    
    # Verifying logging logic fired (via Validator within Engine)
    assert mock_db.create.call_count == 1
    call_args, call_kwargs = mock_db.create.call_args
    assert call_args[0] == "actions"
    assert call_args[1]["action_type"] == "move"


def test_process_update_loop_executes_actions():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    
    current_time = time.time()
    session_id = "sid_1"
    
    # Setup mocks for loading state
    def mock_db_read(collection, doc_id):
        if collection == "sessions":
            return {
                "session_id": session_id,
                "game_id": "dummy",
                "status": SessionStatus.ACTIVE,
                "players": {"p1":{"name": "Alice"}, "p2":{"name": "Bob"}},
                "created_at": current_time,
                "last_action_at": current_time
            }
        elif collection == "game_configs":
            return {"update_interval_ms": 600}
        elif collection == "states":
            return {
                "session_id": session_id,
                "last_update_timestamp": current_time - 1.0,
                "public_state": {"ticks": 1},
                "private_state": {"p1":{"secret": "123"}, "p2":{"secret": "456"}}
            }
        return None
        
    mock_db.read.side_effect = mock_db_read
    
    # Setup pending actions mapping
    mock_db.query.return_value = [
        {"id": "act1", "player_id": "p1", "action_type": "valid_move", "payload": "did_thing", "timestamp": current_time},
        {"id": "act2", "player_id": "p2", "action_type": "invalid_move", "payload": "fail", "timestamp": current_time}
    ]
    
    # Execute loop
    engine.process_update_loop(session_id)
    
    # Verifying updates
    assert mock_scheduler.schedule_next_update.call_count == 1
    mock_scheduler.schedule_next_update.assert_called_with(session_id, 600)
    
    # Ensure invalid action wasn't applied but ticked state was saved
    assert mock_db.update.call_count >= 2 # State update, and marking valid/invalid actions
    
    # Find the state update
    state_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "states"]
    assert len(state_updates) == 1
    updated_state = state_updates[0][0][2]
    
    assert updated_state["public_state"]["ticks"] == 2 # 1+1 tick applied
    assert updated_state["public_state"]["last_move"] == "did_thing" # only applied valid action
