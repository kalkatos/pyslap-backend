import pytest
import random
import time
from typing import Any
from games.battleship import BattleshipGameRules
from pyslap.models.domain import Action, GameState, Player, SessionStatus
from pyslap.core.engine import PySlapEngine
from unittest.mock import MagicMock

@pytest.fixture
def battleship_rules ():
    return BattleshipGameRules()

def test_battleship_initial_state (battleship_rules):
    players = [Player("p1", "Alice"), Player("p2", "Bob")]
    state = battleship_rules.create_game_state(players, {})
    
    ps = state.public_state
    assert ps["phase"] == "setup"
    assert ps["total_hits_needed"] == 17 # 5+4+3+3+2
    assert "p1" in state.private_state
    assert "p2" in state.private_state

def test_battleship_placement_validation (battleship_rules):
    players = [Player("p1", "Alice"), Player("p2", "Bob")]
    state = battleship_rules.create_game_state(players, {})
    
    # Valid placement
    valid_placements = [
        {"name": "Carrier", "x": 0, "y": 0, "orientation": "H"},
        {"name": "Battleship", "x": 0, "y": 1, "orientation": "H"},
        {"name": "Cruiser", "x": 0, "y": 2, "orientation": "H"},
        {"name": "Submarine", "x": 0, "y": 3, "orientation": "H"},
        {"name": "Destroyer", "x": 0, "y": 4, "orientation": "H"},
    ]
    action = Action("sid", "p1", "place_ships", {"placements": valid_placements}, time.time())
    assert battleship_rules.validate_action(action, state) is True

    # Invalid placement: Overlap
    invalid_placements = [
        {"name": "Carrier", "x": 0, "y": 0, "orientation": "H"},
        {"name": "Battleship", "x": 0, "y": 0, "orientation": "H"}, # Overlap!
        {"name": "Cruiser", "x": 0, "y": 2, "orientation": "H"},
        {"name": "Submarine", "x": 0, "y": 3, "orientation": "H"},
        {"name": "Destroyer", "x": 0, "y": 4, "orientation": "H"},
    ]
    action_overlap = Action("sid", "p1", "place_ships", {"placements": invalid_placements}, time.time())
    assert battleship_rules.validate_action(action_overlap, state) is False

def test_battleship_full_match_with_bot (battleship_rules):
    rng = random.Random(42) # Deterministic
    players = [Player("p1", "Alice")]
    state = battleship_rules.create_game_state(players, {"use_bot": True})
    
    # 1. Setup Phase: Player 1 places ships
    valid_placements = [
        {"name": "Carrier", "x": 0, "y": 0, "orientation": "H"},
        {"name": "Battleship", "x": 0, "y": 1, "orientation": "H"},
        {"name": "Cruiser", "x": 0, "y": 2, "orientation": "H"},
        {"name": "Submarine", "x": 0, "y": 3, "orientation": "H"},
        {"name": "Destroyer", "x": 0, "y": 4, "orientation": "H"},
    ]
    action_place = Action("sid", "p1", "place_ships", {"placements": valid_placements}, time.time())
    state = battleship_rules.apply_action(action_place, state, rng)
    
    assert state.public_state["phase"] == "playing"
    assert state.public_state["turn"] == "p1"
    assert "computer" in state.private_state
    assert state.private_state["computer"]["ships_placed"] is True

    # 2. Playing Phase: P1 fires a shot
    # We know the bot generates a valid random board. Since we used seed 42, we could check it,
    # but let's just fire at (0, 0) and check the logic works.
    action_fire = Action("sid", "p1", "fire_shot", {"x": 5, "y": 5}, time.time())
    state = battleship_rules.apply_action(action_fire, state, rng)
    
    assert len(state.public_state["shots"]["p1"]) == 1
    assert state.public_state["turn"] == "computer" # Switched turn!
    
    # 3. Apply Bot Update Tick (Bot should fire)
    state = battleship_rules.apply_update_tick(state, 100, rng)
    assert len(state.public_state["shots"].get("computer", [])) == 1
    assert state.public_state["turn"] == "p1" # Switched back!

def test_battleship_win_condition (battleship_rules):
    rng = random.Random(42)
    players = [Player("p1", "Alice"), Player("p2", "Bob")]
    state = battleship_rules.create_game_state(players, {})
    
    # Setup boards manually for testing
    # Both players place ships
    placements = [
        {"name": "Carrier", "x": 0, "y": 0, "orientation": "H"},
        {"name": "Battleship", "x": 0, "y": 1, "orientation": "H"},
        {"name": "Cruiser", "x": 0, "y": 2, "orientation": "H"},
        {"name": "Submarine", "x": 0, "y": 3, "orientation": "H"},
        {"name": "Destroyer", "x": 0, "y": 4, "orientation": "H"},
    ]
    state = battleship_rules.apply_action(Action("sid", "p1", "place_ships", {"placements": placements}, 0), state, rng)
    state = battleship_rules.apply_action(Action("sid", "p2", "place_ships", {"placements": placements}, 0), state, rng)
    
    # P1 fires a shot that hits
    # Total hits needed is 17. 
    # Let's bypass the loop and simulate 16 hits on P2.
    state.private_state["p2"]["hits_received"] = 16
    state.public_state["turn"] = "p1"
    
    # Last shot (hit)
    action_win = Action("sid", "p1", "fire_shot", {"x": 0, "y": 0}, 0)
    state = battleship_rules.apply_action(action_win, state, rng)
    
    assert state.public_state["phase"] == "game_over"
    assert state.public_state["winner"] == "p1"
    assert state.is_game_over is True
