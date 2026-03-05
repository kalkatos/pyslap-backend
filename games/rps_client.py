"""
Terminal runner for Rock Paper Scissors using the pyslap backend.
Usage:  python games/run_rps.py
"""

import asyncio
import os
import sys
import tempfile

# Ensure project root is on sys.path so pyslap imports work.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any
from local.sql_database import SQLiteDatabase
from local.local_server import LocalScheduler
from local.local_entrypoint import LocalEntrypoint
from pyslap.core.engine import PySlapEngine
from games.rps import RpsGameRules
from pyslap.models.domain import GameState


PLAYER_ID = "player1"
COMPUTER_ID = "computer"
PLAYER_NAME = "Player"
COMPUTER_NAME = "Computer"
GAME_ID = "rps"


db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
db = SQLiteDatabase(db_path=db_path)
scheduler = LocalScheduler()  # callbacks unused; we drive the loop manually
engine = PySlapEngine(
    db=db,
    scheduler=scheduler,
    games_registry={GAME_ID: RpsGameRules()},
)
entrypoint = LocalEntrypoint(engine)


async def _read_input(prompt: str, timeout: float) -> str | None:
    """Read a line from stdin with a timeout (seconds). Returns None on timeout."""
    loop = asyncio.get_event_loop()
    print(prompt, end="", flush=True)
    try:
        future = loop.run_in_executor(None, sys.stdin.readline)
        result = await asyncio.wait_for(future, timeout=timeout)
        return result.strip()
    except asyncio.TimeoutError:
        return None


def _get_state(session_id: str, player_id: str, token: str) -> GameState:
    return entrypoint.get_state(session_id, player_id, token)


def _get_data(session_id: str, player_id: str, token: str, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    return entrypoint.get_data(session_id, player_id, token, collection, filters)


def _send_action(session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any]) -> None:
    return entrypoint.send_action(session_id, player_id, token, action_type, payload)


async def run_client() -> None:
    # ---- bootstrap engine ----
    # Use a temp file because SQLiteDatabase opens a new connection per call,
    # and :memory: databases are per-connection (each gets a blank DB).

    try:
        # ---- create session ----
        result = engine.create_session(GAME_ID, PLAYER_ID, PLAYER_NAME)
        if result is None:
            print("Failed to create session.")
            return

        session_id = result["session_id"]
        token = result["token"]

        print("=" * 40)
        print("  ROCK  PAPER  SCISSORS  (best of 3)")
        print("=" * 40)

        # ---- game loop ----
        while True:
            # Fetch current state
            state = _get_state(session_id, PLAYER_ID, token)

            ps = state.public_state
            phase = ps.get("phase", "")

            match phase:
                case "waiting_for_move":
                    rnd = ps.get("round", "?")
                    print(f"\n--- Round {rnd} ---")
                    user_input = await _read_input("Enter your move (R/P/S): ", timeout=10.0)

                    if user_input is None:
                        # Force one more tick so the engine's timeout logic fires
                        engine.process_update_loop(session_id)
                        print("\nNo move made within 10 seconds, terminating match.")
                        break

                    choice = user_input.upper()
                    if choice not in ("R", "P", "S"):
                        print(f"Invalid move '{user_input}'. Please enter R, P, or S.")
                        continue

                    # Register the action
                    _send_action(
                        session_id=session_id,
                        player_id=PLAYER_ID,
                        token=token,
                        action_type="move",
                        payload={"choice": choice},
                    )

                    import random
                    computer_choice = random.choice(["R", "P", "S"])

                    # Register the action
                    _send_action(
                        session_id=session_id,
                        player_id=COMPUTER_ID,
                        token=token,
                        action_type="move",
                        payload={"choice": computer_choice},
                    )

                case "round_complete":
                    print("\nRound complete...")
                    move_names = {"R": "Rock", "P": "Paper", "S": "Scissors"}
                    pm = ps.get("last_p1_move", "?")
                    cm = ps.get("last_p2_move", "?")

                    print(f"Player move:   {move_names.get(pm, pm)}")
                    print(f"Computer move: {move_names.get(cm, cm)}")

                    winner = ps.get("last_round_winner", "")
                    if winner == "p1":
                        print(">> You win this round!")
                    elif winner == "p2":
                        print(">> Computer wins this round!")
                    else:
                        print(">> It's a draw! Play again.")
                    print(f"\nScore: Player {ps.get('p1_score', 0)} - {ps.get('p2_score', 0)} Computer")

                case "game_over":
                    print("\n" + "=" * 40)
                    print(f"  FINAL SCORE:  Player {ps['p1_score']} - {ps['p2_score']} Computer")
                    if ps.get("winner") == "p1":
                        print("  🎉  You win the match!")
                    else:
                        print("  💻  Computer wins the match!")
                    print("=" * 40)
                    break
                case "timeout":
                    print("\nNo move made within 10 seconds, terminating match.")
                    break
                case _:
                    print(f"\n! ! ! Unknown phase: {phase}")

            await asyncio.sleep(0.5)

        print("\nThanks for playing!")
        quit()
    finally:
        # Clean up temp database file
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    asyncio.run(run_client())
