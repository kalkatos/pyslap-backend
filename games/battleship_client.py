"""
Terminal runner for Battleship using the pyslap HTTP backend.
Usage:
  1. Start the server:  python -m uvicorn local.app:app
  2. Run this client:   python games/battleship_client.py
"""

import asyncio
import sys
import time
import uuid
import jwt
import httpx
from typing import Any, List, Dict

GRID_SIZE = 10
SHIPS_CONFIG = {
    "Carrier": 5,
    "Battleship": 4,
    "Cruiser": 3,
    "Submarine": 3,
    "Destroyer": 2,
}

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

# --- HTTP Helpers ---

async def start_session (client, base_url, game_id, auth_token, custom_data=None):
    payload = {"game_id": game_id, "auth_token": auth_token}
    if custom_data: payload["custom_data"] = custom_data
    resp = await client.post(f"{base_url}/session", json=payload)
    return resp.json() if resp.status_code == 200 else None

async def get_state (client, base_url, session_id, player_id, token):
    try:
        resp = await client.get(f"{base_url}/state", params={"session_id": session_id, "player_id": player_id, "token": token})
        return resp.json() if resp.status_code == 200 else None
    except Exception: return None

async def send_action (client, base_url, session_id, player_id, token, action_type, payload, nonce):
    try:
        resp = await client.post(f"{base_url}/action", json={
            "session_id": session_id, "player_id": player_id, "token": token,
            "action_type": action_type, "payload": payload, "nonce": nonce
        })
        return resp.status_code == 200
    except Exception: return False

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

async def read_input (prompt: str) -> str:
    loop = asyncio.get_event_loop()
    print(prompt, end="", flush=True)
    result = await loop.run_in_executor(None, sys.stdin.readline)
    return result.strip()

# --- Main Client Logic ---

async def run_client (config: dict):
    base_url = config["base_url"]
    player_id = config["player_id"]
    token_key = "pyslap_default_external_secret_32_bytes_min"
    auth_token = jwt.encode({"player_id": player_id, "name": config["player_name"], "exp": time.time() + 3600}, token_key, algorithm="HS256")

    async with httpx.AsyncClient(timeout=10.0) as client:
        custom_data = {"use_bot": config["use_bot"]}
        if config["matchmaking"]: custom_data["matchmaking"] = True
        if config["create_lobby"]: custom_data["create_lobby"] = True
        if config["join_lobby"]: custom_data["join_lobby"] = config["join_lobby"]

        res = await start_session(client, base_url, config["game_id"], auth_token, custom_data)
        if not res: return print("Failed to start session.")

        session_id, token = res["session_id"], res["token"]
        print(f"Session started! ID: {session_id}")
        if res.get("lobby_id"): print(f"Lobby Code: {res['lobby_id']}")

        nonce = 0
        last_version = -1
        placements_done = False

        while True:
            state = await get_state(client, base_url, session_id, player_id, token)
            if not state: 
                await asyncio.sleep(1)
                continue
            
            if state["state_version"] == last_version:
                await asyncio.sleep(0.5)
                continue
            last_version = state["state_version"]

            ps = state["public_state"]
            phase = ps["phase"]

            if phase == "setup":
                if not placements_done:
                    print("\n--- SHIP PLACEMENT PHASE ---")
                    placements = []
                    # Simple auto-placement for speed, or manual? Let's do a mix or just random for now to keep it usable
                    choice = await read_input("Do you want (A)uto-placement or (M)anual? ")
                    if choice.upper() == "A":
                        # Generate random valid placement
                        import random as lrand
                        temp_board = [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
                        from games.battleship import _is_valid_placement, _place_ship
                        for name, length in SHIPS_CONFIG.items():
                            while True:
                                x, y, o = lrand.randint(0,9), lrand.randint(0,9), lrand.choice(['H', 'V'])
                                if _is_valid_placement(x, y, length, o, temp_board):
                                    _place_ship(x, y, length, o, name, temp_board)
                                    placements.append({"name": name, "x": x, "y": y, "orientation": o})
                                    break
                    else:
                        for name, length in SHIPS_CONFIG.items():
                            print(f"Placing {name} (length {length})")
                            while True:
                                try:
                                    raw = await read_input("Enter x y orientation(H/V) (e.g. 0 0 H): ")
                                    parts = raw.split()
                                    x, y, o = int(parts[0]), int(parts[1]), parts[2].upper()
                                    placements.append({"name": name, "x": x, "y": y, "orientation": o})
                                    break
                                except: print("Invalid input. Try again.")

                    nonce += 1
                    await send_action(client, base_url, session_id, player_id, token, "place_ships", {"placements": placements}, nonce)
                    placements_done = True
                    print("Ships placed. Waiting for opponent...")

            elif phase == "playing":
                print("\n" + "="*40)
                my_shots = ps["shots"].get(player_id, [])
                print_shots(my_shots, "YOUR ATTACKS")
                
                # We can't see opponent's full board, but we see our own ships and their hits
                my_private = state["private_state"]
                print_board(my_private["board"], "YOUR BOARD")

                if ps["turn"] == player_id:
                    print("\n>> YOUR TURN!")
                    while True:
                        try:
                            raw = await read_input("Enter coordinates to fire (x y): ")
                            parts = raw.split()
                            x, y = int(parts[0]), int(parts[1])
                            nonce += 1
                            if await send_action(client, base_url, session_id, player_id, token, "fire_shot", {"x": x, "y": y}, nonce):
                                break
                            else: print("Invalid shot or already fired there.")
                        except: print("Invalid input. Use 'x y'.")
                else:
                    print("\nWaiting for opponent's turn...")

            elif phase == "game_over":
                print("\n" + "!"*40)
                if ps["winner"] == player_id: print("  VICTORY! All enemy ships sunk!")
                else: print("  DEFEAT! Your fleet has been destroyed.")
                print("!"*40)
                break

if __name__ == "__main__":
    asyncio.run(run_client(parse_args()))
