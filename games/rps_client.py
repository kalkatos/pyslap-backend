"""
Terminal runner for Rock Paper Scissors using the pyslap HTTP backend.
Usage:
  1. Start the server:  uvicorn local.app:app
  2. Run this client:   python games/rps_client.py
"""

import asyncio
import sys
import uuid
from typing import Any

import httpx

base_url = "http://localhost:8000"
use_bot = True
matchmaking = True
create_lobby = False
join_lobby = None
player_id = "undefined-unknown"
game_id = "rps"

for i, arg in enumerate(sys.argv):
    if arg == "--port" or arg == "-p":
        if i + 1 < len(sys.argv):
            base_url = f"http://localhost:{sys.argv[i + 1]}"
        else:
            print("Error: --port requires a port number")
            sys.exit(1)
    elif arg == "--bot" or arg == "-b":
        use_bot = True
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
        print("  --bot or -b          -> play against a bot")
        print("  --create-lobby or -l -> create a private lobby")
        print("  --join or -j [ID]    -> join a private lobby")
        print("  --port or -p [PORT]  -> connect to specific port")
        print("  --game or -g [ID]    -> play a specific game (default: rps)")
        print("  --help or -h         -> show this help message")
        sys.exit(0)

player_name = player_id.upper()


# ---------------------------------------------------------------------------
# HTTP helpers (async)
# ---------------------------------------------------------------------------

async def _start_session (client: httpx.AsyncClient, game_id: str, player_id: str, player_name: str, custom_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "game_id": game_id,
        "player_id": player_id,
        "player_name": player_name,
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


async def _get_state (client: httpx.AsyncClient, session_id: str, player_id: str, token: str) -> dict[str, Any]:
    resp = await client.get(f"{base_url}/state", params={
        "session_id": session_id,
        "player_id": player_id,
        "token": token,
    })
    resp.raise_for_status()
    return resp.json()


async def _send_action (client: httpx.AsyncClient, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any], nonce: int) -> None:
    resp = await client.post(f"{base_url}/action", json={
        "session_id": session_id,
        "player_id": player_id,
        "token": token,
        "action_type": action_type,
        "payload": payload,
        "nonce": nonce,
    })
    resp.raise_for_status()


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
        return result.strip()
    except asyncio.TimeoutError:
        return "<timeout>"


# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

async def run_client () -> None:
    async with httpx.AsyncClient() as client:
        # ---- create session ----
        custom_data: dict[str, Any] = {"use_bot": use_bot}
        if matchmaking:
            custom_data["matchmaking"] = True
        if create_lobby:
            custom_data["create_lobby"] = True
        if join_lobby:
            custom_data["join_lobby"] = join_lobby
            
        result = await _start_session(client, game_id, player_id, player_name, custom_data=custom_data)
        if result is None:
            return

        session_id = result["session_id"]
        token = result["token"]
        lobby_id = result.get("lobby_id")

        print("=" * 40)
        print("  ROCK  PAPER  SCISSORS  (best of 3)")
        if lobby_id and create_lobby:
            print(f"  LOBBY CREATED. Code: {lobby_id}")
            print(f"  Share with your opponent: python games/rps_client.py --join={lobby_id}")
        elif lobby_id and join_lobby:
            print(f"  LOBBY: {lobby_id}")
        print("=" * 40)

        last_state_version = -1
        client_nonce = 0

        # ---- game loop ----
        while True:
            # Fetch current state
            state = await _get_state(client, session_id, player_id, token)

            current_version = state.get("state_version", 0)
            if current_version == last_state_version:
                await asyncio.sleep(0.1)
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
                    await _send_action(
                        client,
                        session_id=session_id,
                        player_id=player_id,
                        token=token,
                        action_type="move",
                        payload={"choice": choice},
                        nonce=client_nonce,
                    )

                case "round_complete":
                    move_names = {"R": "Rock", "P": "Paper", "S": "Scissors"}
                    
                    private_state = state.get("private_state", {})
                    my_raw = private_state.get("my_choice")
                    opp_raw = private_state.get("opponent_choice")
                    my_move = move_names.get(my_raw, "?") if my_raw else "?"
                    opp_move = move_names.get(opp_raw, "?") if opp_raw else "?"

                    print(f"Your move:     {my_move}")
                    print(f"Opponent move: {opp_move}")

                    winner = ps.get("last_round_winner", "")
                    
                    # Logic depends on whether my_score matched winner id. 
                    # If this player is p1, and p1 won, it's a win for them.
                    # A better way is matching the choices. 
                    # But since the game logic already computes score, we'll check if my_score increased.
                    # Or we just print out the new scores directly:
                    my_score = private_state.get("my_score", 0)
                    opp_score = private_state.get("opponent_score", 0)

                    # Determine round win from score difference if we just look at winner 
                    # Let's derive it directly from backend: we know winner is 'p1' or 'p2'.
                    # Or we can see who beats who to print the correct message:
                    if winner == "draw":
                        print(">> It's a draw! Play again.")
                    elif winner in ("p1", "p2"):
                        # If backend gave us "p1_score", we know our own my_score mapped to it.
                        print(f">> Round complete!")

                    print(f"\nScore: You {my_score} - {opp_score} Opponent")

                case "game_over":
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
