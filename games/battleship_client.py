"""
Terminal runner for Battleship using the pyslap HTTP backend.
Usage:
  1. Start the server:  python -m uvicorn local.app:app
  2. Run this client:   python games/battleship_client.py
"""

import asyncio
from pathlib import Path
import sys
import uuid
from typing import Any, List, Dict

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from games.client_base import ClientRuntime, GameClientBase

# Helpers to keep client independent of server-side logic
def _is_valid_placement (x: int, y: int, length: int, orientation: str, existing_board: List[List[str]]) -> bool:
    if x < 0 or y < 0 or x >= GRID_SIZE or y >= GRID_SIZE:
        return False
    if orientation == 'H':
        if x + length > 10: return False
        for i in range(length):
            if existing_board[y][x + i] != "": return False
    elif orientation == 'V':
        if y + length > 10: return False
        for i in range(length):
            if existing_board[y + i][x] != "": return False
    else:
        return False
    return True

def _place_ship (x: int, y: int, length: int, orientation: str, ship_name: str, board: List[List[str]]):
    if orientation == 'H':
        for i in range(length):
            board[y][x + i] = ship_name
    else:
        for i in range(length):
            board[y + i][x] = ship_name

GRID_SIZE = 10
SHIPS_CONFIG = {
    "Carrier": 5,
    "Battleship": 4,
    "Cruiser": 3,
    "Submarine": 3,
    "Destroyer": 2,
}


class BattleshipClient(GameClientBase):
    def __init__(self):
        self.placements_done = False

    async def on_session_started(
        self,
        runtime: ClientRuntime,
        session_response: dict[str, Any],
        config: dict[str, Any],
        input_func,
    ) -> None:
        print(f"Session started! ID: {runtime.session_id}")
        if session_response.get("lobby_id"):
            print(f"Lobby Code: {session_response['lobby_id']}")

    async def handle_state(
        self,
        runtime: ClientRuntime,
        state: dict[str, Any],
        input_func,
    ) -> bool:
        ps = state["public_state"]
        phase = ps["phase"]

        if phase == "setup":
            if not self.placements_done:
                print("\n--- SHIP PLACEMENT PHASE ---")
                placements = []
                temp_board = [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
                choice = await self.read_input("Do you want (A)uto-placement or (M)anual? ")
                if choice.upper() == "A":
                    import random as lrand

                    for name, length in SHIPS_CONFIG.items():
                        while True:
                            x, y, orientation = lrand.randint(0, 9), lrand.randint(0, 9), lrand.choice(["H", "V"])
                            if _is_valid_placement(x, y, length, orientation, temp_board):
                                _place_ship(x, y, length, orientation, name, temp_board)
                                placements.append({"name": name, "x": x, "y": y, "orientation": orientation})
                                break
                else:
                    for name, length in SHIPS_CONFIG.items():
                        print(f"Placing {name} (length {length})")
                        while True:
                            try:
                                raw = await self.read_input("Enter x y orientation(H/V) (e.g. 0 0 H): ")
                                parts = raw.split()
                                x, y, orientation = int(parts[0]), int(parts[1]), parts[2].upper()
                                if not _is_valid_placement(x, y, length, orientation, temp_board):
                                    print("Invalid placement (out of bounds, overlap, or bad orientation). Try again.")
                                    continue
                                _place_ship(x, y, length, orientation, name, temp_board)
                                placements.append({"name": name, "x": x, "y": y, "orientation": orientation})
                                break
                            except Exception:
                                print("Invalid input. Try again.")

                runtime.nonce += 1
                ok = await self.send_action(
                    runtime.client,
                    runtime.base_url,
                    runtime.session_id,
                    runtime.player_id,
                    runtime.token,
                    "place_ships",
                    {"placements": placements},
                    runtime.nonce,
                )
                if ok:
                    self.placements_done = True
                    print("Ships placed. Waiting for opponent...")
                else:
                    # Reprocess setup state so player can retry ship placement.
                    runtime.last_state_version = -1
                    print("Could not submit placements. Please try again.")
            return False

        if phase == "playing":
            print("\n" + "=" * 40)
            my_shots = ps["shots"].get(runtime.player_id, [])
            print_shots(my_shots, "YOUR ATTACKS")

            my_private = state["private_state"]
            print_board(my_private["board"], "YOUR BOARD")

            if ps["turn"] == runtime.player_id:
                print("\n>> YOUR TURN!")
                while True:
                    try:
                        raw = await self.read_input("Enter coordinates to fire (x y): ")
                        parts = raw.split()
                        x, y = int(parts[0]), int(parts[1])
                        runtime.nonce += 1
                        if await self.send_action(
                            runtime.client,
                            runtime.base_url,
                            runtime.session_id,
                            runtime.player_id,
                            runtime.token,
                            "fire_shot",
                            {"x": x, "y": y},
                            runtime.nonce,
                        ):
                            break
                        print("Invalid shot or already fired there.")
                    except Exception:
                        print("Invalid input. Use 'x y'.")
            else:
                print("\nWaiting for opponent's turn...")
            return False

        if phase == "game_over":
            print("\n" + "!" * 40)
            if ps["winner"] == runtime.player_id:
                print("  VICTORY! All enemy ships sunk!")
            else:
                print("  DEFEAT! Your fleet has been destroyed.")
            print("!" * 40)
            runtime.final_state = state
            return True

        return False

def parse_args ():
    config = {
        "base_url": "http://localhost:8000",
        "use_bot": False,
        "matchmaking": False,
        "create_lobby": False,
        "join_lobby": None,
        "player_id": f"p-{uuid.uuid4().hex[:4]}",
        "game_id": "battleship",
    }

    for i, arg in enumerate(sys.argv):
        if arg in ("--port", "-p") and i + 1 < len(sys.argv):
            config["base_url"] = f"http://localhost:{sys.argv[i + 1]}"
        elif arg in ("--matchmaking", "-m"):
            config["matchmaking"] = True
        elif arg in ("--create-lobby", "-l"):
            config["matchmaking"] = True
            config["create_lobby"] = True
        elif arg in ("--join", "-j") and i + 1 < len(sys.argv):
            config["matchmaking"] = True
            config["join_lobby"] = sys.argv[i + 1].upper()
        elif arg in ("--id", "-i") and i + 1 < len(sys.argv):
            config["player_id"] = sys.argv[i + 1]
        elif arg in ("--bot", "-b"):
            config["use_bot"] = True

    if not config["matchmaking"] and not config["create_lobby"] and not config["join_lobby"]:
        config["use_bot"] = True
    
    config["player_name"] = config["player_id"].upper()
    return config

# --- Terminal UI Helpers ---

def print_board (board: List[List[str]], title: str):
    print(f"\n--- {title} ---")
    print("  " + " ".join(str(i) for i in range(GRID_SIZE)))
    for y, row in enumerate(board):
        display_row = []
        for cell in row:
            if cell == "": display_row.append(".")
            elif cell == "H": display_row.append("X") # Hit
            elif cell == "M": display_row.append("O") # Miss
            else: display_row.append(cell[0]) # Ship initial
        print(f"{y} " + " ".join(display_row))

def print_shots (shots: List[Dict], title: str):
    board = [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
    for s in shots:
        board[s["y"]][s["x"]] = "H" if s["result"] == "hit" else "M"
    print_board(board, title)

# --- Main Client Logic ---

async def run_client(config: dict):
    return await BattleshipClient().run_client(config)

if __name__ == "__main__":
    asyncio.run(run_client(parse_args()))
