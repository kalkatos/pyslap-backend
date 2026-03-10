"""
Unit tests for RpsGameRules (games/rps.py).
Run with:  python -m pytest tests/test_rps.py -v
"""

import random
from unittest.mock import patch

from pyslap.models.domain import Action, GameState
from games.rps import RpsGameRules, _resolve_round, _initial_public_state


# ------------------------------------------------------------------ helpers
def _make_state (phase: str = "waiting_for_move", players: list[str] | None = None, **overrides) -> GameState:
    ps = _initial_public_state()
    ps["phase"] = phase
    ps.update(overrides)
    default_players = players or ["p1", "p2"]
    private_state = {
        pid: {"choice": "", "my_choice": None, "opponent_choice": None, "my_score": 0, "opponent_score": 0}
        for pid in default_players
    }
    return GameState(session_id="test", public_state=ps, private_state=private_state)


def _make_action(choice: str = "R", computer_choice: str = "S", player_id: str = "p1") -> Action:
    return Action(
        session_id="test",
        player_id=player_id,
        action_type="move",
        payload={"choice": choice, "computer_choice": computer_choice},
        timestamp=0.0,
    )


rules = RpsGameRules()


# -------------------------------------------------------- _resolve_round
class TestResolveRound:
    def test_draw(self):
        assert _resolve_round("R", "R") == "draw"

    def test_player_wins(self):
        assert _resolve_round("R", "S") == "p1"
        assert _resolve_round("S", "P") == "p1"
        assert _resolve_round("P", "R") == "p1"

    def test_computer_wins(self):
        assert _resolve_round("R", "P") == "p2"
        assert _resolve_round("S", "R") == "p2"
        assert _resolve_round("P", "S") == "p2"


# -------------------------------------------------------- validate_action
class TestValidateAction:
    def test_valid_moves(self):
        state = _make_state()
        for ch in ("R", "P", "S"):
            assert rules.validate_action(_make_action(ch), state) is True

    def test_lowercase_accepted(self):
        state = _make_state()
        for ch in ("r", "p", "s"):
            assert rules.validate_action(_make_action(ch), state) is True

    def test_invalid_choice(self):
        state = _make_state()
        bad = _make_action("X")
        assert rules.validate_action(bad, state) is False

    def test_wrong_phase(self):
        state = _make_state(phase="round_complete")
        assert rules.validate_action(_make_action("R"), state) is False

    def test_wrong_action_type(self):
        state = _make_state()
        action = Action(session_id="test", player_id="p1", action_type="chat", payload={"choice": "R"}, timestamp=0)
        assert rules.validate_action(action, state) is False


# -------------------------------------------------------- apply_action
class TestApplyAction:
    def test_player_wins_round(self):
        state = _make_state()
        state = rules.apply_action(_make_action("R", player_id="p1"), state)
        state = rules.apply_action(_make_action("S", player_id="p2"), state)
        assert state.public_state["last_p1_move"] == "R"
        assert state.public_state["last_p2_move"] == "S"
        assert state.public_state["last_round_winner"] == "p1"
        assert state.public_state["p1_score"] == 1

    def test_computer_wins_round(self):
        state = _make_state()
        state = rules.apply_action(_make_action("S", player_id="p1"), state)
        state = rules.apply_action(_make_action("R", player_id="p2"), state)
        assert state.public_state["last_round_winner"] == "p2"
        assert state.public_state["p2_score"] == 1

    def test_draw_no_score_change(self):
        state = _make_state()
        state = rules.apply_action(_make_action("R", player_id="p1"), state)
        state = rules.apply_action(_make_action("R", player_id="p2"), state)
        assert state.public_state["last_round_winner"] == "draw"
        assert state.public_state["p1_score"] == 0
        assert state.public_state["p2_score"] == 0

    def test_lowercase_input_applies(self):
        state = _make_state()
        state = rules.apply_action(_make_action("r", player_id="p1"), state)
        state = rules.apply_action(_make_action("S", player_id="p2"), state)
        assert state.public_state["last_p1_move"] == "R"
        assert state.public_state["last_round_winner"] == "p1"


# ---------------------------------------------------- best-of-three winner
class TestBestOfThree:
    def test_player_wins_match(self):
        state = _make_state()
        # Win round 1
        state = rules.apply_action(_make_action("R", player_id="p1"), state)
        state = rules.apply_action(_make_action("S", player_id="p2"), state)
        assert state.public_state["phase"] == "round_complete"

        # Transition to next round
        state = rules.apply_update_tick(state, 500)
        assert state.public_state["phase"] == "waiting_for_move"

        # Win round 2
        state = rules.apply_action(_make_action("R", player_id="p1"), state)
        state = rules.apply_action(_make_action("S", player_id="p2"), state)
        assert state.public_state["phase"] == "game_over"
        assert state.public_state["winner"] == "p1"
        assert rules.check_game_over(state) is True

    def test_computer_wins_match(self):
        state = _make_state()
        state = rules.apply_action(_make_action("R", player_id="p1"), state)  # lose
        state = rules.apply_action(_make_action("P", player_id="p2"), state)  # lose
        state = rules.apply_update_tick(state, 500)
        state = rules.apply_action(_make_action("R", player_id="p1"), state)  # lose
        state = rules.apply_action(_make_action("P", player_id="p2"), state)  # lose
        assert state.public_state["winner"] == "p2"
        assert rules.check_game_over(state) is True


# -------------------------------------------------------- timeout
class TestTimeout:
    def test_timeout_marks_game_over(self):
        state = _make_state()
        state = rules.apply_update_tick(state, 10_000)
        assert state.public_state["phase"] == "timeout"
        assert state.is_game_over is True
        assert rules.check_game_over(state) is True

    def test_no_timeout_below_10s(self):
        state = _make_state()
        state = rules.apply_update_tick(state, 9_999)
        assert state.public_state["phase"] == "waiting_for_move"
        assert state.is_game_over is False


# -------------------------------------------------------- prepare_state
class TestPrepareState:
    def test_merges_public_and_private(self):
        state = _make_state()
        state.private_state = {"p1": {"secret": "abc"}}
        result = state.to_player_state("p1")
        assert result.public_state["phase"] == "waiting_for_move"
        assert result.private_state["secret"] == "abc"

    def test_no_private_state(self):
        state = _make_state()
        result = state.to_player_state("p1")
        assert "phase" in result.public_state


# ------------------------------------------------ apply_update_tick init
class TestUpdateTickInit:
    def test_empty_state_gets_initialized(self):
        state = GameState(session_id="test")
        state = rules.apply_update_tick(state, 0)
        assert state.public_state["phase"] == "waiting_for_move"
        assert state.public_state["round"] == 1
