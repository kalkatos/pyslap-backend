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

from local.sql_database import SQLiteDatabase
from local.local_server import LocalScheduler
from pyslap.core.engine import PySlapEngine
from games.rps import RpsGameRules


PLAYER_ID = "player1"
PLAYER_NAME = "Player"
GAME_ID = "rps"


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


async def run_game() -> None:
    # ---- bootstrap engine ----
    # Use a temp file because SQLiteDatabase opens a new connection per call,
    # and :memory: databases are per-connection (each gets a blank DB).
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    try:
        db = SQLiteDatabase(db_path=db_path)
        scheduler = LocalScheduler()  # callbacks unused; we drive the loop manually
        engine = PySlapEngine(
            db=db,
            scheduler=scheduler,
            games_registry={GAME_ID: RpsGameRules()},
        )

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
            # Tick the engine so it can initialise / advance state
            engine.process_update_loop(session_id)

            # Fetch current state
            state_data = db.read("states", session_id)
            if state_data is None:
                break

            ps = state_data.get("public_state", {})
            phase = ps.get("phase", "")

            # ---- handle round_complete: show results then tick again ----
            if phase == "round_complete":
                # Results were already printed after action; just continue
                continue

            # ---- game over / timeout ----
            if phase == "timeout":
                print("\nNo move made within 10 seconds, terminating match.")
                break
            if phase == "game_over":
                print("\n" + "=" * 40)
                print(f"  FINAL SCORE:  Player {ps['player_score']} - {ps['computer_score']} Computer")
                if ps.get("winner") == "player":
                    print("  🎉  You win the match!")
                else:
                    print("  💻  Computer wins the match!")
                print("=" * 40)
                break

            # ---- waiting_for_move ----
            if phase == "waiting_for_move":
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
                engine.register_action(
                    session_id=session_id,
                    player_id=PLAYER_ID,
                    token=token,
                    action_type="move",
                    payload={"choice": choice},
                )

                # Tick to apply the action
                engine.process_update_loop(session_id)

                # Re-read state to show result
                state_data = db.read("states", session_id)
                ps = state_data.get("public_state", {}) if state_data else {}

                move_names = {"R": "Rock", "P": "Paper", "S": "Scissors"}
                pm = ps.get("last_player_move", "?")
                cm = ps.get("last_computer_move", "?")

                print(f"Player move:   {move_names.get(pm, pm)}")
                print(f"Computer move: {move_names.get(cm, cm)}")

                winner = ps.get("last_round_winner", "")
                if winner == "player":
                    print(">> You win this round!")
                elif winner == "computer":
                    print(">> Computer wins this round!")
                else:
                    print(">> It's a draw! Play again.")

                print(f"Score: Player {ps.get('player_score', 0)} - {ps.get('computer_score', 0)} Computer")

        print("\nThanks for playing!")
        quit()
    finally:
        # Clean up temp database file
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    asyncio.run(run_game())
