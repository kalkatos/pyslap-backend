import time
from unittest.mock import MagicMock

from pyslap.core.engine import PySlapEngine
from pyslap.core.game_rules import GameRules
from pyslap.core.test_utils import create_debug_external_token
from pyslap.models.domain import Action, GameState, SessionStatus, Player
from typing import Any, Dict
import random


class MatchmakingGame(GameRules):
    def create_game_state(self, players: list[Player], custom_data: dict[str, Any]) -> GameState:
        is_matchmaking = custom_data.get("matchmaking", False)
        return GameState(session_id="", public_state={"phase": "waiting_for_players" if is_matchmaking else "waiting"}, private_state={})

    def validate_action(self, action: Action, state: GameState) -> bool:
        return True

    def apply_action(self, action: Action, state: GameState, rng: random.Random) -> GameState:
        return state

    def apply_update_tick(self, state: GameState, delta_ms: int, rng: random.Random) -> GameState:
        return state

    def check_game_over(self, state: GameState) -> bool:
        return False
        
    def setup_player_state(self, state: GameState, player: Player) -> GameState:
        state.private_state[player.player_id] = {"joined": True}
        return state


def test_create_matchmaking_session():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"mm_game": MatchmakingGame()}
    
    def mock_db_read(coll, id):
        if coll == "players": return {"id": id, "name": "Player"}
        if coll == "game_configs": return {"update_interval_ms": 1000, "max_players": 2}
        return None
    mock_db.read.side_effect = mock_db_read
    mock_db.query.return_value = []  # No existing waiting sessions
    
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    # Create p1 token
    auth_token = create_debug_external_token("p1", "Alice")
    result = engine.create_session("mm_game", auth_token, custom_data={"matchmaking": True})
    
    assert result is not None
    
    assert mock_db.create.call_count == 2
    args1, kwargs1 = mock_db.create.call_args_list[0] # sessions
    assert args1[0] == "sessions"
    assert args1[1]["status"] == SessionStatus.MATCHMAKING
    
    args2, kwargs2 = mock_db.create.call_args_list[1] # states
    assert args2[1]["public_state"]["phase"] == "waiting_for_players"


def test_join_matchmaking_session():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"mm_game": MatchmakingGame()}
    
    # 1. First player creates session
    def mock_db_read(coll, id):
        if coll == "players":
            return {"id": id, "name": "Player"}
        if coll == "game_configs":
            return {"update_interval_ms": 1000, "max_players": 2}
        if coll == "states":
            return {
                "session_id": "sid_1",
                "last_update_timestamp": time.time(),
                "public_state": {"phase": "waiting_for_players"},
                "private_state": {"p1": {}}
            }
        return None
        
    mock_db.read.side_effect = mock_db_read
    
    # Simulate an existing waiting session
    mock_db.query.return_value = [{
        "id": "sid_1",
        "session_id": "sid_1",
        "game_id": "mm_game",
        "status": SessionStatus.MATCHMAKING,
        "players": {"p1": {"player_id": "p1", "name": "Alice", "token": "t1"}},
        "created_at": time.time(),
        "last_action_at": time.time(),
        "version": 0
    }]
    
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    
    # 2. Second player joins
    auth_token = create_debug_external_token("p2", "Bob")
    result = engine.create_session("mm_game", auth_token, custom_data={"matchmaking": True})
    
    assert result is not None
    assert result.session_id == "sid_1"
    
    # Verify session update to ACTIVE
    assert mock_db.update.call_count >= 2  # Updated session + state
    
    session_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "sessions"]
    assert len(session_updates) == 2 # 1 for CLAIMED, 1 for ACTIVE
    updated_session = session_updates[1][0][2]
    
    assert updated_session["status"] == SessionStatus.ACTIVE
    assert "p1" in updated_session["players"]
    assert "p2" in updated_session["players"]
    
    state_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "states"]
    assert len(state_updates) == 1
    updated_state = state_updates[0][0][2]
    
    assert "p2" in updated_state["private_state"]
    assert updated_state["private_state"]["p2"]["joined"] is True


def test_matchmaking_cas_failure_retries():
    """Test that CAS failure on session update triggers a retry."""
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"mm_game": MatchmakingGame()}

    def mock_db_read(coll, id):
        if coll == "players":
            return {"id": id, "name": "Player"}
        if coll == "game_configs":
            return {"update_interval_ms": 1000, "max_players": 2}
        if coll == "states":
            return {
                "session_id": "sid_1",
                "last_update_timestamp": time.time(),
                "public_state": {"phase": "waiting_for_players"},
                "private_state": {"p1": {}}
            }
        return None

    mock_db.read.side_effect = mock_db_read

    # Return fresh session data on each query call (since code modifies it)
    def mock_query(collection, filters):
        return [{
            "id": "sid_1",
            "session_id": "sid_1",
            "game_id": "mm_game",
            "status": SessionStatus.MATCHMAKING,
            "players": {"p1": {"player_id": "p1", "name": "Alice", "token": "t1"}},
            "created_at": time.time(),
            "last_action_at": time.time(),
            "version": 0
        }]

    mock_db.query.side_effect = mock_query

    # Mock update: 
    # 1. First claim attempt fails (False)
    # 2. Second claim attempt succeeds (True)
    # 3. Session status update to ACTIVE succeeds (True)
    # 4. State update succeeds (True)
    mock_db.update.side_effect = [False, True, True, True]

    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    auth_token = create_debug_external_token("p2", "Bob")
    result = engine.create_session("mm_game", auth_token, custom_data={"matchmaking": True})

    # Despite the first CAS failure, the retry should succeed
    assert result is not None
    assert result.session_id == "sid_1"

    # Verify update was called for sessions
    session_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "sessions"]
    assert len(session_updates) == 3 # 1st fail, 2nd claim, 3rd active


def test_matchmaking_cas_all_retries_exhausted():
    """Test that exhausted CAS retries fall through to creating a new session."""
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"mm_game": MatchmakingGame()}

    def mock_db_read(coll, id):
        if coll == "players":
            return {"id": id, "name": "Player"}
        if coll == "game_configs":
            return {"update_interval_ms": 1000, "max_players": 2}
        if coll == "states":
            return {
                "session_id": "sid_1",
                "last_update_timestamp": time.time(),
                "public_state": {"phase": "waiting_for_players"},
                "private_state": {"p1": {}}
            }
        return None

    mock_db.read.side_effect = mock_db_read

    # Return fresh session data on each query call
    def mock_query(collection, filters):
        return [{
            "id": "sid_1",
            "session_id": "sid_1",
            "game_id": "mm_game",
            "status": SessionStatus.MATCHMAKING,
            "players": {"p1": {"player_id": "p1", "name": "Alice", "token": "t1"}},
            "created_at": time.time(),
            "last_action_at": time.time(),
            "version": 0
        }]

    mock_db.query.side_effect = mock_query

    # Mock update to always fail (CAS always loses)
    mock_db.update.return_value = False

    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    auth_token = create_debug_external_token("p2", "Bob")
    result = engine.create_session("mm_game", auth_token, custom_data={"matchmaking": True})

    # Should fall through to creating a new session
    assert result is not None
    # Verify that create was called (new session creation)
    assert mock_db.create.call_count >= 2


def test_matchmaking_version_incremented_on_join():
    """Test that session version is incremented when a player joins."""
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"mm_game": MatchmakingGame()}

    def mock_db_read(coll, id):
        if coll == "players":
            return {"id": id, "name": "Player"}
        if coll == "game_configs":
            return {"update_interval_ms": 1000, "max_players": 2}
        if coll == "states":
            return {
                "session_id": "sid_1",
                "last_update_timestamp": time.time(),
                "public_state": {"phase": "waiting_for_players"},
                "private_state": {"p1": {}}
            }
        return None

    mock_db.read.side_effect = mock_db_read

    # Return fresh session data on each query call
    def mock_query(collection, filters):
        return [{
            "id": "sid_1",
            "session_id": "sid_1",
            "game_id": "mm_game",
            "status": SessionStatus.MATCHMAKING,
            "players": {"p1": {"player_id": "p1", "name": "Alice", "token": "t1"}},
            "created_at": time.time(),
            "last_action_at": time.time(),
            "version": 0
        }]

    mock_db.query.side_effect = mock_query
    mock_db.update.return_value = True

    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    auth_token = create_debug_external_token("p2", "Bob")
    result = engine.create_session("mm_game", auth_token, custom_data={"matchmaking": True})

    assert result is not None

    # Verify that update was called for sessions
    session_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "sessions"]
    assert len(session_updates) == 2 # 1 for CLAIMED, 1 for ACTIVE

    # Check the call arguments - update is called as:
    # self.db.update("sessions", s_id, updated_session_data, expected_version=current_version)
    call_args, call_kwargs = session_updates[0]
    # args are: (collection, record_id, data)
    assert call_kwargs.get("expected_version") == 0, "expected_version should be 0"

    # Check that the data contains version=1
    updated_data = call_args[2]
    assert updated_data["version"] == 1, "version should be incremented to 1"
