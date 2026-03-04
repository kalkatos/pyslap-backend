"""
Rock Paper Scissors - GameRules implementation for the pyslap backend.
Best-of-three between a player and a computer with random moves.
"""

import random
from typing import Any, Dict, List

from pyslap.core.game_rules import GameRules
from pyslap.models.domain import Action, GameState, Player


VALID_MOVES = {"R", "P", "S"}

# Winner lookup: key beats value
BEATS = {"R": "S", "S": "P", "P": "R"}


def _resolve_round(player_move: str, computer_move: str) -> str:
    """Returns 'player', 'computer', or 'draw'."""
    if player_move == computer_move:
        return "draw"
    if BEATS[player_move] == computer_move:
        return "player"
    return "computer"


def _initial_public_state() -> Dict[str, Any]:
    return {
        "round": 1,
        "player_score": 0,
        "computer_score": 0,
        "phase": "waiting_for_move",
        "last_player_move": None,
        "last_computer_move": None,
        "last_round_winner": None,
        "winner": None,
        "round_start_ms": 0,
    }


class RpsGameRules(GameRules):
    """Best-of-three Rock Paper Scissors against a random computer opponent."""

    # ------------------------------------------------------------------
    # GameRules interface
    # ------------------------------------------------------------------

    def validate_action(self, action: Action, state: GameState) -> bool:
        if state.public_state.get("phase") != "waiting_for_move":
            return False
        if action.action_type != "move":
            return False
        choice = action.payload.get("choice", "").upper()
        return choice in VALID_MOVES

    def apply_action(self, action: Action, state: GameState) -> GameState:
        player_move = action.payload["choice"].upper()
        computer_move = random.choice(list(VALID_MOVES))

        result = _resolve_round(player_move, computer_move)

        ps = state.public_state
        ps["last_player_move"] = player_move
        ps["last_computer_move"] = computer_move
        ps["last_round_winner"] = result

        if result == "player":
            ps["player_score"] += 1
        elif result == "computer":
            ps["computer_score"] += 1
        # draw: no score change, replay the round

        # Check if someone reached 2 wins → game over
        if ps["player_score"] >= 2:
            ps["phase"] = "game_over"
            ps["winner"] = "player"
            state.is_game_over = True
        elif ps["computer_score"] >= 2:
            ps["phase"] = "game_over"
            ps["winner"] = "computer"
            state.is_game_over = True
        else:
            # Next round (only advance round number on non-draw)
            if result != "draw":
                ps["round"] += 1
            ps["phase"] = "round_complete"

        return state

    def apply_update_tick(self, state: GameState, delta_ms: int) -> GameState:
        ps = state.public_state

        # Initialise public_state on very first tick (empty state)
        if not ps:
            state.public_state = _initial_public_state()
            return state

        phase = ps.get("phase")

        # After a round_complete, transition back to waiting
        if phase == "round_complete":
            ps["phase"] = "waiting_for_move"
            ps["round_start_ms"] = 0
            ps["last_player_move"] = None
            ps["last_computer_move"] = None
            ps["last_round_winner"] = None
            return state

        # Timeout check while waiting for a move
        if phase == "waiting_for_move":
            ps["round_start_ms"] = ps.get("round_start_ms", 0) + delta_ms
            if ps["round_start_ms"] >= 10_000:
                ps["phase"] = "timeout"
                state.is_game_over = True

        return state

    def check_game_over(self, state: GameState) -> bool:
        phase = state.public_state.get("phase", "")
        return phase in ("game_over", "timeout")

    def prepare_state(
        self,
        state: GameState,
        player_id: str,
        recent_actions: List[Action],
    ) -> Dict[str, Any]:
        private = state.private_state.get(player_id, {})
        return {**state.public_state, **private}
