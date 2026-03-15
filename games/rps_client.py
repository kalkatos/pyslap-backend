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

base_url = "http://localhost:8000"
use_bot = False
matchmaking = False
create_lobby = False
join_lobby = None
player_id = f"p-{uuid.uuid4().hex[:4]}"
game_id = "rps"

for i, arg in enumerate(sys.argv):
    if arg == "--port" or arg == "-p":
        if i + 1 < len(sys.argv):
            base_url = f"http://localhost:{sys.argv[i + 1]}"
        else:
            print("Error: --port requires a port number")
            sys.exit(1)
    elif arg == "--matchmaking" or arg == "-m":
        matchmaking = True
    elif arg == "--create-lobby" or arg == "-l":
        matchmaking = True
        create_lobby = True
    elif arg == "--join" or arg == "-j":
        if i + 1 < len(sys.argv):
            matchmaking = True
            join_lobby = sys.argv[i + 1].upper()
        else:
            print("Error: --join requires a lobby ID")
            sys.exit(1)
    elif arg == "--id" or arg == "-i":
        if i + 1 < len(sys.argv):
            player_id = sys.argv[i + 1]
        else:
            print("Error: --id requires a player ID")
            sys.exit(1)
    elif arg == "--game" or arg == "-g":
        if i + 1 < len(sys.argv):
            game_id = sys.argv[i + 1]
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

if not matchmaking and not create_lobby and not join_lobby:
    use_bot = True

player_name = player_id.upper()


# ---------------------------------------------------------------------------
# HTTP helpers (async)
# ---------------------------------------------------------------------------

async def _start_session (client: httpx.AsyncClient, game_id: str, auth_token: str, custom_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
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


async def _get_state (client: httpx.AsyncClient, session_id: str, player_id: str, token: str) -> dict[str, Any] | None:
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


async def _send_action (client: httpx.AsyncClient, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any], nonce: int) -> bool:
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

async def _read_input (prompt: str, timeout: float) -> str:
    """Read a line from stdin with a timeout (seconds). Returns None on timeout."""
    loop = asyncio.get_event_loop()
    print(prompt, end="", flush=True)
    try:
        future = loop.run_in_executor(None, sys.stdin.readline)
        result = await asyncio.wait_for(future, timeout=timeout)
        stripped = result.strip()
        if stripped == "":  # EOF on a closed pipe
            return "<timeout>"
        return stripped
    except asyncio.TimeoutError:
        return "<timeout>"


# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

async def run_client () -> None:
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
            
        result = await _start_session(client, game_id, auth_token, custom_data=custom_data)
        if result is None:
            return

        session_id = result["session_id"]
        token = result["token"]
        lobby_id = result.get("lobby_id")

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

        # ---- game loop ----
        while True:
            # Fetch current state
            state = await _get_state(client, session_id, player_id, token)
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
                    print("Waiting for an opponent to join...")
                    last_state_version = -1  # keep printing periodically? No, only prints on version bump
                    # To avoid spamming, we just let it sleep
                    await asyncio.sleep(1.0)

                case "waiting_for_move":
                    if move_submitted:
                        # Move already sent this round; wait silently for opponent
                        await asyncio.sleep(0.25)
                        continue

                    rnd = ps.get("round", "?")
                    print(f"\n--- Round {rnd} ---")
                    user_input = "<empty>"
                    choice = ""

                    while True:
                        user_input = await _read_input("Enter your move (R/P/S): ", timeout=10.0)
                        if user_input == "<timeout>":
                            break
                        choice = user_input.upper()
                        if choice in ("R", "P", "S"):
                            break
                        print(f"Invalid move '{user_input}'. Please enter R, P, or S.")

                    if user_input == "<timeout>":
                        print("\nNo move made within 10 seconds, terminating match.")
                        break

                    # Send the player's move
                    client_nonce += 1
                    ok = await _send_action(
                        client,
                        session_id=session_id,
                        player_id=player_id,
                        token=token,
                        action_type="move",
                        payload={"choice": choice},
                        nonce=client_nonce,
                    )
                    if ok:
                        move_submitted = True
                        print("Waiting for opponent's move...")

                case "round_complete":
                    move_submitted = False
                    move_names = {"R": "Rock", "P": "Paper", "S": "Scissors"}

                    private_state = state.get("private_state", {})
                    my_raw = private_state.get("my_choice")
                    opp_raw = private_state.get("opponent_choice")
                    my_move = move_names.get(my_raw, "?") if my_raw else "?"
                    opp_move = move_names.get(opp_raw, "?") if opp_raw else "?"

                    print(f"Your move:     {my_move}")
                    print(f"Opponent move: {opp_move}")

                    winner = ps.get("last_round_winner", "")
                    my_score = private_state.get("my_score", 0)
                    opp_score = private_state.get("opponent_score", 0)

                    if winner == "draw":
                        print(">> It's a draw! Play again.")
                    elif winner in ("p1", "p2"):
                        print(f">> Round complete!")

                    print(f"\nScore: You {my_score} - {opp_score} Opponent")

                    # Send explicit ack so the engine can clear the gated phase
                    await _send_action(
                        client,
                        session_id=session_id,
                        player_id=player_id,
                        token=token,
                        action_type="ack",
                        payload={},
                        nonce=0,
                    )

                case "game_over":
                    move_submitted = False
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
                    print("\nNo move made within 10 seconds, terminating match.")
                    break

                case _:
                    print(f"\n! ! ! Unknown phase: {phase}")

            await asyncio.sleep(0.1)

        print("\nThanks for playing!")


if __name__ == "__main__":
    asyncio.run(run_client())
