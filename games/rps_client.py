"""
Terminal runner for Rock Paper Scissors using the pyslap HTTP backend.
Usage:
  1. Start the server:  uvicorn local.app:app
  2. Run this client:   python games/rps_client.py
"""

import asyncio
import sys
import time
import uuid
from typing import Any

import jwt

import httpx

def parse_args():
    """Parse CLI arguments and return a config dictionary."""
    config = {
        "base_url": "http://localhost:8000",
        "use_bot": False,
        "matchmaking": False,
        "create_lobby": False,
        "join_lobby": None,
        "player_id": f"p-{uuid.uuid4().hex[:4]}",
        "game_id": "rps",
    }

    for i, arg in enumerate(sys.argv):
        if arg == "--port" or arg == "-p":
            if i + 1 < len(sys.argv):
                config["base_url"] = f"http://localhost:{sys.argv[i + 1]}"
            else:
                print("Error: --port requires a port number")
                sys.exit(1)
        elif arg == "--matchmaking" or arg == "-m":
            config["matchmaking"] = True
        elif arg == "--create-lobby" or arg == "-l":
            config["matchmaking"] = True
            config["create_lobby"] = True
        elif arg == "--join" or arg == "-j":
            if i + 1 < len(sys.argv):
                config["matchmaking"] = True
                config["join_lobby"] = sys.argv[i + 1].upper()
            else:
                print("Error: --join requires a lobby ID")
                sys.exit(1)
        elif arg == "--id" or arg == "-i":
            if i + 1 < len(sys.argv):
                config["player_id"] = sys.argv[i + 1]
            else:
                print("Error: --id requires a player ID")
                sys.exit(1)
        elif arg == "--game" or arg == "-g":
            if i + 1 < len(sys.argv):
                config["game_id"] = sys.argv[i + 1]
            else:
                print("Error: --game requires a game ID")
                sys.exit(1)
        elif arg == "--help" or arg == "-h":
            print("Options:")
            print("  --matchmaking or -m  -> match any player")
            print("  --create-lobby or -l -> create a private lobby")
            print("  --join or -j [ID]    -> join a private lobby")
            print("  --port or -p [PORT]  -> connect to specific port (default: 8000)")
            print("  --game or -g [ID]    -> play a specific game (default: rps)")
            print("  --help or -h         -> show this help message")
            sys.exit(0)

    if not config["matchmaking"] and not config["create_lobby"] and not config["join_lobby"]:
        config["use_bot"] = True
    
    config["player_name"] = config["player_id"].upper()
    return config

# ---------------------------------------------------------------------------
# HTTP helpers (async)
# ---------------------------------------------------------------------------

async def start_session (client: httpx.AsyncClient, base_url: str, game_id: str, auth_token: str, custom_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "game_id": game_id,
        "auth_token": auth_token,
    }
    if custom_data:
        payload["custom_data"] = custom_data
    resp = await client.post(f"{base_url}/session", json=payload)
    if resp.status_code != 200:
        try:
            err_msg = resp.json().get("detail", f"Error: {resp.status_code} - {resp.text}")
        except Exception:
            err_msg = f"Error: {resp.status_code} - {resp.text}"
        print(err_msg)
        return None
    return resp.json()


async def get_state (client: httpx.AsyncClient, base_url: str, session_id: str, player_id: str, token: str) -> dict[str, Any] | None:
    try:
        resp = await client.get(f"{base_url}/state", params={
            "session_id": session_id,
            "player_id": player_id,
            "token": token,
        })
    except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as e:
        print(f"\n[Warning] Network error getting state: {e}")
        return None
    if resp.status_code != 200:
        try:
            err_msg = resp.json().get("detail", f"Error: {resp.status_code} - {resp.text}")
        except Exception:
            err_msg = f"Error: {resp.status_code} - {resp.text}"
        print(f"\n[Warning] Failed to get state: {err_msg}")
        return None
    return resp.json()


async def send_action (client: httpx.AsyncClient, base_url: str, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any], nonce: int) -> bool:
    try:
        resp = await client.post(f"{base_url}/action", json={
            "session_id": session_id,
            "player_id": player_id,
            "token": token,
            "action_type": action_type,
            "payload": payload,
            "nonce": nonce,
        })
    except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as e:
        print(f"\n[Warning] Network error sending action: {e}")
        return False
    if resp.status_code != 200:
        try:
            err_msg = resp.json().get("detail", f"Error: {resp.status_code} - {resp.text}")
        except Exception:
            err_msg = f"Error: {resp.status_code} - {resp.text}"
        print(f"\n[Warning] Failed to send action: {err_msg}")
        return False
    return True


# ---------------------------------------------------------------------------
# Input helper
# ---------------------------------------------------------------------------

async def read_input (prompt: str, timeout: float) -> str:
    """Read a line from stdin with a timeout (seconds). Returns None on timeout."""
    loop = asyncio.get_event_loop()
    print(prompt, end="", flush=True)
    try:
        # Avoid blocking the event loop for a long time
        future = loop.run_in_executor(None, sys.stdin.readline)
        result = await asyncio.wait_for(future, timeout=timeout)
        stripped = result.strip()
        if stripped == "":  # EOF
            return "<timeout>"
        return stripped
    except asyncio.TimeoutError:
        return "<timeout>"


# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

async def run_client (config: dict[str, Any], input_func=None) -> dict[str, Any] | None:
    """Runs the RPS client logic. 
    If input_func is provided, it's used instead of read_input(prompt, timeout).
    input_func should be an async function taking (prompt, phase, round_num) and returning a move.
    """
    base_url = config.get("base_url", "http://localhost:8000")
    player_id = config.get("player_id", "test_player")
    player_name = config.get("player_name", player_id.upper())
    game_id = config.get("game_id", "rps")
    use_bot = config.get("use_bot", False)
    matchmaking = config.get("matchmaking", False)
    create_lobby = config.get("create_lobby", False)
    join_lobby = config.get("join_lobby")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # ---- create session ----
        custom_data: dict[str, Any] = {"use_bot": use_bot}
        if matchmaking:
            custom_data["matchmaking"] = True
        if create_lobby:
            custom_data["create_lobby"] = True
        if join_lobby:
            custom_data["join_lobby"] = join_lobby
            
        # mock external auth token using default external_secret
        auth_token = jwt.encode(
            {"player_id": player_id, "name": player_name, "exp": time.time() + 86400},
            "pyslap_default_external_secret_32_bytes_min",
            algorithm="HS256"
        )
            
        result = await start_session(client, base_url, game_id, auth_token, custom_data=custom_data)
        if result is None:
            return None

        session_id = result["session_id"]
        token = result["token"]
        lobby_id = result.get("lobby_id")

        if not input_func:
            print("=" * 40)
            print("  ROCK  PAPER  SCISSORS  (best of 3)")
            if lobby_id and create_lobby:
                print(f"  LOBBY CREATED. Code: {lobby_id}")
                print(f"  Share with your opponent: python games/rps_client.py --join {lobby_id}")
            elif lobby_id and join_lobby:
                print(f"  LOBBY: {lobby_id}")
            print("=" * 40)

        last_state_version = -1
        client_nonce = 0
        move_submitted = False
        final_state = None

        # ---- game loop ----
        while True:
            # Fetch current state
            state = await get_state(client, base_url, session_id, player_id, token)
            if state is None:
                await asyncio.sleep(1.0)
                continue

            current_version = state.get("state_version", 0)
            if current_version == last_state_version:
                await asyncio.sleep(0.25)
                continue

            last_state_version = current_version

            ps = state["public_state"]
            phase = ps.get("phase", "")

            match phase:
                case "waiting_for_players":
                    if not input_func:
                        print("Waiting for an opponent to join...")
                    await asyncio.sleep(1.0)

                case "waiting_for_move":
                    if move_submitted:
                        await asyncio.sleep(0.25)
                        continue

                    rnd = ps.get("round", "?")
                    choice = ""

                    if input_func:
                        choice = await input_func("Enter move: ", phase, rnd)
                    else:
                        print(f"\n--- Round {rnd} ---")
                        while True:
                            user_input = await read_input("Enter your move (R/P/S): ", timeout=10.0)
                            if user_input == "<timeout>":
                                choice = "<timeout>"
                                break
                            choice = user_input.upper()
                            if choice in ("R", "P", "S"):
                                break
                            print(f"Invalid move '{user_input}'. Please enter R, P, or S.")

                    if choice == "<timeout>":
                        if not input_func:
                            print("\nNo move made within 10 seconds, terminating match.")
                        break

                    # Send the player's move
                    client_nonce += 1
                    ok = await send_action(
                        client,
                        base_url=base_url,
                        session_id=session_id,
                        player_id=player_id,
                        token=token,
                        action_type="move",
                        payload={"choice": choice},
                        nonce=client_nonce,
                    )
                    if ok:
                        move_submitted = True
                        if not input_func:
                            print("Waiting for opponent's move...")

                case "round_complete":
                    move_submitted = False
                    move_names = {"R": "Rock", "P": "Paper", "S": "Scissors"}

                    private_state = state.get("private_state", {})
                    my_raw = private_state.get("my_choice")
                    opp_raw = private_state.get("opponent_choice")
                    my_move = move_names.get(my_raw, "?") if my_raw else "?"
                    opp_move = move_names.get(opp_raw, "?") if opp_raw else "?"

                    if not input_func:
                        print(f"Your move:     {my_move}")
                        print(f"Opponent move: {opp_move}")

                    winner = ps.get("last_round_winner", "")
                    my_score = private_state.get("my_score", 0)
                    opp_score = private_state.get("opponent_score", 0)

                    if not input_func:
                        if winner == "draw":
                            print(">> It's a draw! Play again.")
                        elif winner in ("p1", "p2"):
                            print(f">> Round complete!")
                        print(f"\nScore: You {my_score} - {opp_score} Opponent")

                    # Send explicit ack
                    await send_action(
                        client,
                        base_url=base_url,
                        session_id=session_id,
                        player_id=player_id,
                        token=token,
                        action_type="ack",
                        payload={},
                        nonce=0,
                    )

                case "game_over":
                    final_state = state
                    move_submitted = False
                    if not input_func:
                        move_names = {"R": "Rock", "P": "Paper", "S": "Scissors"}
                        private_state = state.get("private_state", {})
                        my_raw = private_state.get("my_choice")
                        opp_raw = private_state.get("opponent_choice")
                        my_move = move_names.get(my_raw, "?") if my_raw else "?"
                        opp_move = move_names.get(opp_raw, "?") if opp_raw else "?"
                        
                        print(f"Your move:     {my_move}")
                        print(f"Opponent move: {opp_move}")

                        my_score = private_state.get("my_score", 0)
                        opp_score = private_state.get("opponent_score", 0)

                        winner = ps.get("last_round_winner", "")
                        if winner == "draw":
                            print(">> It's a draw! Play again.")
                        else:
                            print(">> Round complete!")

                        print("\n" + "=" * 40)
                        print(f"  FINAL SCORE:  You {my_score} - {opp_score} Opponent")
                        if my_score > opp_score:
                            print("  🎉  You win the match!")
                        elif opp_score > my_score:
                            print("  😔  Opponent wins the match!")
                        else:
                            print("  🤝  Match drawn!")
                        print("=" * 40)
                    break

                case "timeout":
                    if not input_func:
                        print("\nNo move made within 10 seconds, terminating match.")
                    break

                case _:
                    if not input_func:
                        print(f"\n! ! ! Unknown phase: {phase}")

            await asyncio.sleep(0.1)

        if not input_func:
            print("\nThanks for playing!")
        
        return final_state


if __name__ == "__main__":
    cl_config = parse_args()
    asyncio.run(run_client(cl_config))
