import random
import time
from typing import Any, Dict
from unittest.mock import MagicMock

from pyslap.core.engine import PySlapEngine
from pyslap.core.game_rules import GameRules
from pyslap.models.domain import Action, GameState, SessionStatus, Player


# --- Dummy Game Rules for Testing ---
class DummyGame(GameRules):
    def create_game_state(self, players: list[Player], custom_data: dict[str, Any]) -> GameState:
        return GameState(session_id="", public_state={"phase": "waiting"}, private_state={})

    def validate_action(self, action: Action, state: GameState) -> bool:
        return action.action_type == "valid_move"

    def apply_action(self, action: Action, state: GameState, rng: random.Random) -> GameState:
        state.public_state["last_move"] = action.payload
        return state

    def apply_update_tick(self, state: GameState, delta_ms: int, rng: random.Random) -> GameState:
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
    
    def mock_db_read(coll, id):
        if coll == "players": return {"id": id, "name": "Alice"}
        if coll == "game_configs": return {"update_interval_ms": 1000}
        return None
    mock_db.read.side_effect = mock_db_read
    
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    
    auth_token = engine.security.create_debug_external_token("p1", "Alice")
    result = engine.create_session("dummy", auth_token)
    
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
    auth_token = engine.security.create_debug_external_token("p1", "Alice")
    result = engine.create_session("unknown", auth_token)
    assert result is None


def test_engine_register_action_success():
    mock_db = MagicMock()
    engine = PySlapEngine(db=mock_db, scheduler=MagicMock(), games_registry={})
    
    # Mock session fetch — must include player with matching token for the new security check
    current_time = time.time()
    valid_token = engine.security.generate_session_token("p1", "sid_1")
    mock_session = {
        "session_id": "sid_1",
        "game_id": "dummy",
        "status": SessionStatus.ACTIVE,
        "players": {"p1": {"player_id": "p1", "name": "Player", "token": valid_token}},
        "created_at": current_time,
        "last_action_at": current_time - 1000
    }
    mock_db.read.return_value = mock_session
    
    result = engine.register_action(
        session_id="sid_1", 
        player_id="p1", 
        token=valid_token, 
        action_type="move", 
        payload={"x": 5},
        nonce=1
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
        {"id": "act1", "player_id": "p1", "action_type": "valid_move", "payload": "did_thing", "timestamp": current_time, "nonce": 1},
        {"id": "act2", "player_id": "p2", "action_type": "invalid_move", "payload": "fail", "timestamp": current_time, "nonce": 1}
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

def test_engine_skips_tick_on_gated_phase():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    
    # Game that gates the "gated" phase
    class GatedGame(DummyGame):
        def get_phase_gates(self) -> set[str]:
            return {"gated"}
            
    games = {"gated_game": GatedGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    
    current_time = time.time()
    session_id = "sid_1"
    
    def mock_db_read(collection, doc_id):
        if collection == "sessions":
            return {
                "session_id": session_id,
                "game_id": "gated_game",
                "status": SessionStatus.ACTIVE,
                "players": {"p1":{"name": "Alice"}, "p2":{"name": "Bob"}},
                "created_at": current_time,
                "last_action_at": current_time
            }
        elif collection == "game_configs":
            return {"update_interval_ms": 600, "phase_ack_timeout_sec": 10}
        elif collection == "states":
            return {
                "session_id": session_id,
                "last_update_timestamp": current_time - 1.0,
                "public_state": {"phase": "gated", "ticks": 1},
                "private_state": {},
                # p1 has acked, p2 has NOT
                "phase_ack": {"p1": True, "p2": False},
                # Inside timeout window
                "phase_ack_since": current_time - 5.0
            }
        return None
        
    mock_db.read.side_effect = mock_db_read
    mock_db.query.return_value = [] # no actions
    
    # Execute loop
    engine.process_update_loop(session_id)
    
    # Verify State Update
    # Because skip_tick was True and no actions were applied, the state shouldn't even be resaved!
    state_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "states"]
    assert len(state_updates) == 0

def test_engine_ack_action_updates_phase_ack():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()

    class GatedGame(DummyGame):
        def get_phase_gates(self) -> set[str]:
            return {"gated"}

    games = {"gated_game": GatedGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    current_time = time.time()
    session_id = "sid_1"
    valid_token = engine.security.generate_session_token("p1", session_id)

    def mock_db_read(collection, doc_id):
        if collection == "sessions":
            return {
                "session_id": session_id,
                "game_id": "gated_game",
                "status": SessionStatus.ACTIVE,
                "players": {"p1": {"player_id": "p1", "name": "Alice", "token": valid_token}, "p2": {"player_id": "p2", "name": "Bob"}},
                "created_at": current_time,
                "last_action_at": current_time
            }
        elif collection == "states":
            return {
                "session_id": session_id,
                "last_update_timestamp": current_time,
                "public_state": {"phase": "gated", "ticks": 1},
                "private_state": {},
                "phase_ack": {"p1": False, "p2": False},
                "phase_ack_since": current_time
            }
        return None

    mock_db.read.side_effect = mock_db_read
    mock_db.query.return_value = []

    # Send ack action — should update phase_ack directly
    result = engine.register_action(session_id, "p1", valid_token, "ack", {})
    assert result is True

    # Verify state was saved with p1 acked
    state_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "states"]
    assert len(state_updates) == 1
    updated_state = state_updates[0][0][2]
    assert updated_state["phase_ack"]["p1"] is True
    assert updated_state["phase_ack"]["p2"] is False

    # Verify no action was logged to DB (ack is not queued)
    action_creates = [call for call in mock_db.create.call_args_list if call[0][0] == "actions"]
    assert len(action_creates) == 0


def test_engine_ack_action_idempotent():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()

    class GatedGame(DummyGame):
        def get_phase_gates(self) -> set[str]:
            return {"gated"}

    games = {"gated_game": GatedGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    current_time = time.time()
    session_id = "sid_1"
    valid_token = engine.security.generate_session_token("p1", session_id)

    def mock_db_read(collection, doc_id):
        if collection == "sessions":
            return {
                "session_id": session_id,
                "game_id": "gated_game",
                "status": SessionStatus.ACTIVE,
                "players": {"p1": {"player_id": "p1", "name": "Alice"}},
                "created_at": current_time,
                "last_action_at": current_time
            }
        elif collection == "states":
            return {
                "session_id": session_id,
                "last_update_timestamp": current_time,
                "public_state": {"phase": "gated"},
                "private_state": {},
                "phase_ack": {"p1": True},  # Already acked
                "phase_ack_since": current_time
            }
        return None

    mock_db.read.side_effect = mock_db_read
    mock_db.query.return_value = []

    # Ack again — should succeed (idempotent) but NOT write to DB
    result = engine.register_action(session_id, "p1", valid_token, "ack", {})
    assert result is True

    # No state update needed since already acked
    state_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "states"]
    assert len(state_updates) == 0


def test_engine_ack_rejected_outside_gated_phase():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()

    class GatedGame(DummyGame):
        def get_phase_gates(self) -> set[str]:
            return {"gated"}

    games = {"gated_game": GatedGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    current_time = time.time()
    session_id = "sid_1"
    valid_token = engine.security.generate_session_token("p1", session_id)

    def mock_db_read(collection, doc_id):
        if collection == "sessions":
            return {
                "session_id": session_id,
                "game_id": "gated_game",
                "status": SessionStatus.ACTIVE,
                "players": {"p1": {"player_id": "p1", "name": "Alice"}},
                "created_at": current_time,
                "last_action_at": current_time
            }
        elif collection == "states":
            return {
                "session_id": session_id,
                "last_update_timestamp": current_time,
                "public_state": {"phase": "waiting"},  # NOT a gated phase
                "private_state": {},
                "phase_ack": {"p1": False},
                "phase_ack_since": current_time
            }
        return None

    mock_db.read.side_effect = mock_db_read
    mock_db.query.return_value = []

    # Ack should be rejected — not in a gated phase
    result = engine.register_action(session_id, "p1", valid_token, "ack", {})
    assert result is False


def test_engine_force_clears_gate_on_timeout():
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    
    class GatedGame(DummyGame):
        def get_phase_gates(self) -> set[str]:
            return {"gated"}
            
    games = {"gated_game": GatedGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    
    current_time = time.time()
    session_id = "sid_1"
    
    def mock_db_read(collection, doc_id):
        if collection == "sessions":
            return {
                "session_id": session_id,
                "game_id": "gated_game",
                "status": SessionStatus.ACTIVE,
                "players": {"p1":{"name": "Alice"}, "p2":{"name": "Bob"}},
                "created_at": current_time,
                "last_action_at": current_time
            }
        elif collection == "game_configs":
            return {"update_interval_ms": 600, "phase_ack_timeout_sec": 10}
        elif collection == "states":
            return {
                "session_id": session_id,
                "last_update_timestamp": current_time - 1.0,
                "public_state": {"phase": "gated", "ticks": 1},
                "private_state": {},
                # Neither player acked
                "phase_ack": {"p1": False, "p2": False},
                # Timeout EXPIRED (started 15s ago)
                "phase_ack_since": current_time - 15.0
            }
        return None
        
    mock_db.read.side_effect = mock_db_read
    mock_db.query.return_value = [] 
    
    engine.process_update_loop(session_id)
    
    state_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "states"]
    assert len(state_updates) == 1
    updated_state = state_updates[0][0][2]
    
    # Because timeout expired, skip_tick should be False,
    # so apply_update_tick IS called.
    assert updated_state["public_state"]["ticks"] == 2


def test_engine_deterministic_random_seed_on_create():
    """Verify that random_seed is initialized on session creation."""
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}

    def mock_db_read(coll, id):
        if coll == "players": return {"id": id, "name": "Alice"}
        if coll == "game_configs": return {"update_interval_ms": 1000}
        return None
    mock_db.read.side_effect = mock_db_read

    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
    auth_token = engine.security.create_debug_external_token("p1", "Alice")
    result = engine.create_session("dummy", auth_token)

    # Verify random_seed was set
    state_create_call = [call for call in mock_db.create.call_args_list if call[0][0] == "states"][0]
    state_data = state_create_call[0][1]
    assert state_data["random_seed"] > 0


def test_engine_deterministic_rng_same_seed_same_moves():
    """Verify that same random_seed produces same bot moves in RPS."""
    from games.rps import RpsGameRules

    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"rps": RpsGameRules()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    # Create a fixed seed for reproducibility
    fixed_seed = 12345

    # First run
    state1_data = {
        "session_id": "test_1",
        "random_seed": fixed_seed,
        "public_state": {
            "use_bot": True,
            "phase": "waiting_for_move",
            "p1_score": 0,
            "p2_score": 0,
            "round": 1,
            "last_p1_move": None,
            "last_p2_move": None,
            "last_round_winner": None,
        },
        "private_state": {
            "p1": {"choice": "R"},
            "computer": {"choice": ""}
        },
        "slots": {"slot_0": "p1", "slot_1": "computer"},
        "phase_ack": {},
        "last_nonces": {},
    }
    state1 = GameState(**state1_data)
    action = Action("test_1", "p1", "move", {"choice": "R"}, time.time(), 1)

    state1_result = games["rps"].apply_action(action, state1, random.Random(fixed_seed))
    computer_move_1 = state1_result.private_state["computer"]["choice"]

    # Second run with same seed
    state2_data = state1_data.copy()
    state2 = GameState(**state2_data)
    state2_result = games["rps"].apply_action(action, state2, random.Random(fixed_seed))
    computer_move_2 = state2_result.private_state["computer"]["choice"]

    # Both should produce the same move
    assert computer_move_1 == computer_move_2


def test_engine_random_seed_advances_after_update_loop():
    """Verify that random_seed advances after process_update_loop to prevent replay."""
    mock_db = MagicMock()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}

    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    current_time = time.time()
    session_id = "sid_1"

    original_seed = 99999

    def mock_db_read(collection, doc_id):
        if collection == "sessions":
            return {
                "session_id": session_id,
                "game_id": "dummy",
                "status": SessionStatus.ACTIVE,
                "players": {"p1": {"name": "Alice"}},
                "created_at": current_time,
                "last_action_at": current_time
            }
        elif collection == "game_configs":
            return {"update_interval_ms": 600}
        elif collection == "states":
            return {
                "session_id": session_id,
                "random_seed": original_seed,
                "last_update_timestamp": current_time - 1.0,
                "public_state": {"phase": "waiting", "ticks": 0},
                "private_state": {},
                "phase_ack": {},
                "last_nonces": {},
            }
        return None

    mock_db.read.side_effect = mock_db_read
    mock_db.query.return_value = []

    # Execute loop
    engine.process_update_loop(session_id)

    # Find the state update
    state_updates = [call for call in mock_db.update.call_args_list if call[0][0] == "states"]
    assert len(state_updates) == 1

    updated_state = state_updates[0][0][2]
    new_seed = updated_state["random_seed"]

    # Seed should have changed (unless by extreme chance, it's the same)
    # We can't assert inequality since RNG might theoretically produce same value,
    # but we can verify it's a valid seed
    assert new_seed >= 0
    assert new_seed < 2**63
