"""
Battleship - GameRules implementation for the pyslap backend.
10x10 grid, standard ship set, hidden board logic using private state.
"""

import random
from typing import Any, List, Dict, Optional
from pyslap.core.game_rules import GameRules
from pyslap.models.domain import Action, GameState, Player

# Grid Size
GRID_SIZE = 10

# Ship Configurations: (name, length)
SHIPS_CONFIG = {
    "Carrier": 5,
    "Battleship": 4,
    "Cruiser": 3,
    "Submarine": 3,
    "Destroyer": 2,
}

# Possible shot results
RESULT_MISS = "miss"
RESULT_HIT = "hit"
RESULT_SUNK = "sunk"

def _is_valid_placement (x: int, y: int, length: int, orientation: str, existing_board: List[List[str]]) -> bool:
    """Checks if a ship of 'length' at (x, y) with 'orientation' ('H' or 'V') fits and doesn't overlap."""
    if orientation == 'H':
        if x + length > GRID_SIZE: return False
        for i in range(length):
            if existing_board[y][x + i] != "": return False
    elif orientation == 'V':
        if y + length > GRID_SIZE: return False
        for i in range(length):
            if existing_board[y + i][x] != "": return False
    else:
        return False
    return True

def _place_ship (x: int, y: int, length: int, orientation: str, ship_name: str, board: List[List[str]]):
    """Mutates the board to place the ship."""
    if orientation == 'H':
        for i in range(length):
            board[y][x + i] = ship_name
    else:
        for i in range(length):
            board[y + i][x] = ship_name

def _generate_random_board (rng: random.Random) -> List[List[str]]:
    """Generates a valid random board for the bot."""
    board = [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
    for name, length in SHIPS_CONFIG.items():
        placed = False
        while not placed:
            x, y = rng.randint(0, GRID_SIZE-1), rng.randint(0, GRID_SIZE-1)
            orientation = rng.choice(['H', 'V'])
            if _is_valid_placement(x, y, length, orientation, board):
                _place_ship(x, y, length, orientation, name, board)
                placed = True
    return board

class BattleshipGameRules (GameRules):
    """
    Standard Battleship implementation.
    Phases: 'setup' -> 'playing' -> 'game_over'
    """

    def get_phase_gates (self) -> set[str]:
        # Optionally gate transitions if we want players to ack phase changes.
        # For now, we'll use automatic state transitions for simplicity.
        return set()

    def get_slot_priority (self) -> list[str]:
        return ["slot_0", "slot_1"]

    def create_game_state (self, players: list[Player], custom_data: dict[str, Any]) -> GameState:
        use_bot = custom_data.get("use_bot", False)
        
        # Initialize players' private states
        private_state = {}
        for player in players:
            private_state[player.player_id] = {
                "board": [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)],
                "ships_placed": False,
                "hits_received": 0,
            }
        
        # Handle Bot
        slots = {}
        if use_bot:
            # Bot board will be populated during 'setup' or first tick
            private_state["computer"] = {
                "board": [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)], 
                "ships_placed": False,
                "hits_received": 0,
            }
            slots["slot_1"] = "computer"

        total_ships_length = sum(SHIPS_CONFIG.values())

        return GameState(
            session_id="",
            public_state={
                "phase": "setup",
                "use_bot": use_bot,
                "turn": None, # Will be set once playing starts
                "shots": {}, # player_id -> list of {"x", "y", "result"}
                "winner": None,
                "total_hits_needed": total_ships_length,
            },
            private_state=private_state,
            slots=slots,
            is_game_over=False,
            last_update_timestamp=0,
        )

    def validate_action (self, action: Action, state: GameState) -> bool:
        phase = state.public_state.get("phase")
        player_id = action.player_id
        
        if phase == "setup":
            if action.action_type != "place_ships": return False
            if state.private_state.get(player_id, {}).get("ships_placed"): return False
            
            # Validate placement payload
            placements = action.payload.get("placements", [])
            if len(placements) != len(SHIPS_CONFIG): return False
            
            # Temporary board to check overlaps
            temp_board = [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
            placed_names = set()
            for p in placements:
                name = p.get("name")
                if name not in SHIPS_CONFIG or name in placed_names: return False
                x, y = p.get("x", -1), p.get("y", -1)
                orient = p.get("orientation", "").upper()
                if not _is_valid_placement(x, y, SHIPS_CONFIG[name], orient, temp_board):
                    return False
                _place_ship(x, y, SHIPS_CONFIG[name], orient, name, temp_board)
                placed_names.add(name)
            return True

        elif phase == "playing":
            if action.action_type != "fire_shot": return False
            if state.public_state.get("turn") != player_id: return False
            
            x, y = action.payload.get("x", -1), action.payload.get("y", -1)
            if not (0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE): return False
            
            # Check if already shot there
            past_shots = state.public_state.get("shots", {}).get(player_id, [])
            for s in past_shots:
                if s["x"] == x and s["y"] == y: return False
            return True

        return False

    def apply_action (self, action: Action, state: GameState, rng: random.Random) -> GameState:
        phase = state.public_state.get("phase")
        player_id = action.player_id

        if phase == "setup":
            # Store placement in private state
            placements = action.payload["placements"]
            board = state.private_state[player_id]["board"]
            for p in placements:
                _place_ship(p["x"], p["y"], SHIPS_CONFIG[p["name"]], p["orientation"].upper(), p["name"], board)
            state.private_state[player_id]["ships_placed"] = True
            
            # Check if all (human) players are ready
            all_ready = True
            for pid, pstate in state.private_state.items():
                if pid != "computer" and not pstate.get("ships_placed"):
                    all_ready = False
            
            if all_ready:
                # If bot exists, finalize its board
                if state.public_state.get("use_bot"):
                    state.private_state["computer"]["board"] = _generate_random_board(rng)
                    state.private_state["computer"]["ships_placed"] = True
                
                # Start game!
                state.public_state["phase"] = "playing"
                # Pick starting player: prefer p1/slot_0
                p1_id = state.slots.get("slot_0")
                state.public_state["turn"] = p1_id or player_id

        elif phase == "playing":
            x, y = action.payload["x"], action.payload["y"]
            opponent_id = [pid for pid in state.private_state if pid != player_id][0]
            
            # Check for hit in opponent's board (private)
            ship_hit = state.private_state[opponent_id]["board"][y][x]
            result = RESULT_HIT if ship_hit != "" else RESULT_MISS
            
            if result == RESULT_HIT:
                state.private_state[opponent_id]["hits_received"] += 1
                # Update player private view (success feedback)
                state.update_private_state(player_id, {"last_shot_result": RESULT_HIT})
            else:
                state.update_private_state(player_id, {"last_shot_result": RESULT_MISS})

            # Record in public state
            if player_id not in state.public_state["shots"]:
                state.public_state["shots"][player_id] = []
            state.public_state["shots"][player_id].append({"x": x, "y": y, "result": result})

            # Check for Win
            needed = state.public_state["total_hits_needed"]
            if state.private_state[opponent_id]["hits_received"] >= needed:
                state.public_state["phase"] = "game_over"
                state.public_state["winner"] = player_id
                state.is_game_over = True
            else:
                # Switch Turn
                state.public_state["turn"] = opponent_id

        return state

    def apply_update_tick (self, state: GameState, delta_ms: int, rng: random.Random) -> GameState:
        phase = state.public_state.get("phase")
        if phase == "playing" and state.public_state.get("use_bot"):
            # Bot turn?
            if state.public_state.get("turn") == "computer":
                # Execute random shot
                opponent_id = [pid for pid in state.private_state if pid != "computer"][0]
                
                # Find valid target
                past_shots = state.public_state["shots"].get("computer", [])
                past_set = {(s["x"], s["y"]) for s in past_shots}
                coords = [(x, y) for x in range(GRID_SIZE) for y in range(GRID_SIZE) if (x, y) not in past_set]
                
                if coords:
                    shot_x, shot_y = rng.choice(coords)
                    
                    # Apply bot shot
                    ship_hit = state.private_state[opponent_id]["board"][shot_y][shot_x]
                    result = RESULT_HIT if ship_hit != "" else RESULT_MISS
                    
                    if result == RESULT_HIT:
                        state.private_state[opponent_id]["hits_received"] += 1
                    
                    if "computer" not in state.public_state["shots"]:
                        state.public_state["shots"]["computer"] = []
                    state.public_state["shots"]["computer"].append({"x": shot_x, "y": shot_y, "result": result})
                    
                    # Win check
                    needed = state.public_state["total_hits_needed"]
                    if state.private_state[opponent_id]["hits_received"] >= needed:
                        state.public_state["phase"] = "game_over"
                        state.public_state["winner"] = "computer"
                        state.is_game_over = True
                    else:
                        state.public_state["turn"] = opponent_id

        return state

    def check_game_over (self, state: GameState) -> bool:
        return state.public_state.get("phase") == "game_over"
