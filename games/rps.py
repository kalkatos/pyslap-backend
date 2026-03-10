"""
Rock Paper Scissors - GameRules implementation for the pyslap backend.
Best-of-three between a player and a computer with random moves.
"""

from typing import Any

from pyslap.core.game_rules import GameRules
from pyslap.models.domain import Action, GameState, Player


VALID_MOVES = {"R", "P", "S"}

# Winner lookup: key beats value
BEATS = {"R": "S", "S": "P", "P": "R"}


def _resolve_round(p1_move: str, p2_move: str) -> str:
    """Returns 'player', 'computer', or 'draw'."""
    if p1_move == p2_move:
        return "draw"
    if BEATS[p1_move] == p2_move:
        return "p1"
    return "p2"


def _initial_public_state() -> dict[str, Any]:
    return {
        "round": 1,
        "p1_score": 0,
        "p2_score": 0,
        "phase": "waiting_for_move",
        "last_p1_move": None,
        "last_p2_move": None,
        "last_round_winner": None,
        "winner": None,
        "round_start_ms": 0,
    }


class RpsGameRules(GameRules):
    """Best-of-three Rock Paper Scissors against a random computer opponent."""

    # ------------------------------------------------------------------
    # GameRules interface
    # ------------------------------------------------------------------

    def get_phase_gates(self) -> set[str]:
        return {"round_complete"}

    def create_game_state(self, players: list[Player], custom_data: dict[str, Any]) -> GameState:
        private_state = {}
        for player in players:
            private_state[player.player_id] = {
                "choice": "",
                "my_choice": None,
                "opponent_choice": None,
                "my_score": 0,
                "opponent_score": 0,
            }
        use_bot = custom_data.get("use_bot", False)
        if use_bot:
            private_state["computer"] = {
                "choice": "",
                "my_choice": None,
                "opponent_choice": None,
                "my_score": 0,
                "opponent_score": 0,
            }

        is_matchmaking = custom_data.get("matchmaking", False)
        initial_phase = "waiting_for_players" if is_matchmaking else "waiting_for_move"

        return GameState(
            session_id="",
            public_state={
                "use_bot": use_bot,
                "round": 1,
                "p1_score": 0,
                "p2_score": 0,
                "phase": initial_phase,
                "last_p1_move": None,
                "last_p2_move": None,
                "last_round_winner": None,
                "winner": None,
                "round_start_ms": 0,
            },
            private_state=private_state,
            is_game_over=False,
            last_update_timestamp=0,
        )

    def setup_player_state(self, state: GameState, player: Player) -> GameState:
        state.private_state[player.player_id] = {
            "choice": "",
            "my_choice": None,
            "opponent_choice": None,
            "my_score": 0,
            "opponent_score": 0,
        }

        # If we have reached the required number of players, start the game immediately
        if len(state.private_state) >= 2 and state.public_state.get("phase") == "waiting_for_players":
            state.public_state["phase"] = "waiting_for_move"
            state.public_state["round_start_ms"] = 0
        
        return state

    def validate_action(self, action: Action, state: GameState) -> bool:
        if state.public_state.get("phase") != "waiting_for_move":
            return False
        if action.action_type != "move":
            return False
        choice = action.payload.get("choice", "").upper()
        return choice in VALID_MOVES

    def apply_action(self, action: Action, state: GameState) -> GameState:
        choice = action.payload["choice"].upper()
        state.private_state[action.player_id]["choice"] = choice

        if len(state.private_state) < 2:
            return state

        import random
        ps = state.public_state
        use_bot = ps.get("use_bot", False)

        if use_bot and len(state.private_state) == 2 and "computer" in state.private_state:
            # If the human player just made a move, automatically generate the computer's move
            # Check if the human has a move
            human_id = [p for p in state.private_state if p != "computer"][0]
            if state.private_state[human_id].get("choice") in VALID_MOVES:
                state.private_state["computer"]["choice"] = random.choice(list(VALID_MOVES))

        choices = []
        for player_id in state.private_state:
            move = state.private_state[player_id]
            if move is None or "choice" not in move or not move["choice"] or move["choice"] not in VALID_MOVES:
                return state
            choices.append(move["choice"])

        result = _resolve_round(choices[0], choices[1])

        ps = state.public_state
        ps["last_p1_move"] = choices[0]
        ps["last_p2_move"] = choices[1]
        ps["last_round_winner"] = result

        if result == "p1":
            ps["p1_score"] += 1
        elif result == "p2":
            ps["p2_score"] += 1
        # draw: no score change, replay the round

        # Inject personalized values into private state for each player
        player_ids = list(state.private_state.keys())
        p1_id, p2_id = player_ids[0], player_ids[1]

        state.private_state[p1_id]["my_choice"] = choices[0]
        state.private_state[p1_id]["opponent_choice"] = choices[1]
        state.private_state[p1_id]["my_score"] = ps["p1_score"]
        state.private_state[p1_id]["opponent_score"] = ps["p2_score"]
        
        state.private_state[p2_id]["my_choice"] = choices[1]
        state.private_state[p2_id]["opponent_choice"] = choices[0]
        state.private_state[p2_id]["my_score"] = ps["p2_score"]
        state.private_state[p2_id]["opponent_score"] = ps["p1_score"]

        # Check if someone reached 2 wins → game over
        if ps["p1_score"] >= 2:
            ps["phase"] = "game_over"
            ps["winner"] = "p1"
            state.is_game_over = True
        elif ps["p2_score"] >= 2:
            ps["phase"] = "game_over"
            ps["winner"] = "p2"
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

        if phase == "waiting_for_players":
            if len(state.private_state) >= 2:
                ps["phase"] = "waiting_for_move"
                ps["round_start_ms"] = 0
            # Wait endlessly for players or implement a lobby timeout.
            return state

        # After a round_complete, transition back to waiting
        if phase == "round_complete":
            ps["phase"] = "waiting_for_move"
            ps["round_start_ms"] = 0
            ps["last_p1_move"] = None
            ps["last_p2_move"] = None
            ps["last_round_winner"] = None
            for p in state.private_state:
                state.private_state[p]["choice"] = ""
                state.private_state[p]["my_choice"] = None
                state.private_state[p]["opponent_choice"] = None
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

