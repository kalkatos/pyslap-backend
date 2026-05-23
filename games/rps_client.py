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

from games.client_base import ClientRuntime, GameClientBase, InputFunc

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


class RpsClient(GameClientBase):
    def __init__(self):
        self.move_submitted = False

    async def on_session_started(
        self,
        runtime: ClientRuntime,
        session_response: dict[str, Any],
        config: dict[str, Any],
        input_func: InputFunc | None,
    ) -> None:
        if input_func:
            return

        print("=" * 40)
        print("  ROCK  PAPER  SCISSORS  (best of 3)")
        if session_response.get("lobby_id") and config.get("create_lobby"):
            lobby_id = session_response["lobby_id"]
            print(f"  LOBBY CREATED. Code: {lobby_id}")
            print(f"  Share with your opponent: python games/rps_client.py --join {lobby_id}")
        elif session_response.get("lobby_id") and config.get("join_lobby"):
            print(f"  LOBBY: {session_response['lobby_id']}")
        print("=" * 40)

    async def handle_state(
        self,
        runtime: ClientRuntime,
        state: dict[str, Any],
        input_func: InputFunc | None,
    ) -> bool:
        ps = state["public_state"]
        phase = ps.get("phase", "")

        if phase == "waiting_for_players":
            if not input_func:
                print("Waiting for an opponent to join...")
            return False

        if phase == "waiting_for_move":
            if self.move_submitted:
                return False

            rnd = ps.get("round", "?")
            if input_func:
                choice = await input_func("Enter move: ", phase, rnd)
            else:
                print(f"\n--- Round {rnd} ---")
                while True:
                    user_input = await self.read_input_with_timeout("Enter your move (R/P/S): ", timeout=10.0)
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
                runtime.final_state = state
                return True

            runtime.nonce += 1
            ok = await self.send_action(
                runtime.client,
                base_url=runtime.base_url,
                session_id=runtime.session_id,
                player_id=runtime.player_id,
                token=runtime.token,
                action_type="move",
                payload={"choice": choice},
                nonce=runtime.nonce,
            )
            if ok:
                self.move_submitted = True
                if not input_func:
                    print("Waiting for opponent's move...")
            return False

        if phase == "round_complete":
            self.move_submitted = False
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
                    print(">> Round complete!")
                print(f"\nScore: You {my_score} - {opp_score} Opponent")

            await self.send_action(
                runtime.client,
                base_url=runtime.base_url,
                session_id=runtime.session_id,
                player_id=runtime.player_id,
                token=runtime.token,
                action_type="ack",
                payload={},
                nonce=0,
            )
            return False

        if phase == "game_over":
            runtime.final_state = state
            self.move_submitted = False
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
            return True

        if phase == "timeout":
            runtime.final_state = state
            if not input_func:
                print("\nNo move made within 10 seconds, terminating match.")
            return True

        if not input_func:
            print(f"\n! ! ! Unknown phase: {phase}")
        return False

async def run_client(config: dict[str, Any], input_func=None) -> dict[str, Any] | None:
    return await RpsClient().run_client(config, input_func=input_func)


if __name__ == "__main__":
    cl_config = parse_args()
    try:
        asyncio.run(run_client(cl_config))
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
