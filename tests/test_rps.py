"""
Unit tests for RpsGameRules (games/rps.py).
Run with:  python -m pytest tests/test_rps.py -v
"""

import random
from unittest.mock import patch, MagicMock

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
        rng = random.Random(42)
        state = rules.apply_action(_make_action("R", player_id="p1"), state, rng)
        state = rules.apply_action(_make_action("S", player_id="p2"), state, rng)
        assert state.public_state["last_p1_move"] == "R"
        assert state.public_state["last_p2_move"] == "S"
        assert state.public_state["last_round_winner"] == "p1"
        assert state.public_state["p1_score"] == 1

    def test_computer_wins_round(self):
        state = _make_state()
        rng = random.Random(42)
        state = rules.apply_action(_make_action("S", player_id="p1"), state, rng)
        state = rules.apply_action(_make_action("R", player_id="p2"), state, rng)
        assert state.public_state["last_round_winner"] == "p2"
        assert state.public_state["p2_score"] == 1

    def test_draw_no_score_change(self):
        state = _make_state()
        rng = random.Random(42)
        state = rules.apply_action(_make_action("R", player_id="p1"), state, rng)
        state = rules.apply_action(_make_action("R", player_id="p2"), state, rng)
        assert state.public_state["last_round_winner"] == "draw"
        assert state.public_state["p1_score"] == 0
        assert state.public_state["p2_score"] == 0

    def test_lowercase_input_applies(self):
        state = _make_state()
        rng = random.Random(42)
        state = rules.apply_action(_make_action("r", player_id="p1"), state, rng)
        state = rules.apply_action(_make_action("S", player_id="p2"), state, rng)
        assert state.public_state["last_p1_move"] == "R"
        assert state.public_state["last_round_winner"] == "p1"


# ---------------------------------------------------- best-of-three winner
class TestBestOfThree:
    def test_player_wins_match(self):
        state = _make_state()
        rng = random.Random(42)
        # Win round 1
        state = rules.apply_action(_make_action("R", player_id="p1"), state, rng)
        state = rules.apply_action(_make_action("S", player_id="p2"), state, rng)
        assert state.public_state["phase"] == "round_complete"

        # Transition to next round
        state = rules.apply_update_tick(state, 500, rng)
        assert state.public_state["phase"] == "waiting_for_move"

        # Win round 2
        state = rules.apply_action(_make_action("R", player_id="p1"), state, rng)
        state = rules.apply_action(_make_action("S", player_id="p2"), state, rng)
        assert state.public_state["phase"] == "game_over"
        assert state.public_state["winner"] == "p1"
        assert rules.check_game_over(state) is True

    def test_computer_wins_match(self):
        state = _make_state()
        rng = random.Random(42)
        state = rules.apply_action(_make_action("R", player_id="p1"), state, rng)  # lose
        state = rules.apply_action(_make_action("P", player_id="p2"), state, rng)  # lose
        state = rules.apply_update_tick(state, 500, rng)
        state = rules.apply_action(_make_action("R", player_id="p1"), state, rng)  # lose
        state = rules.apply_action(_make_action("P", player_id="p2"), state, rng)  # lose
        assert state.public_state["winner"] == "p2"
        assert rules.check_game_over(state) is True


# -------------------------------------------------------- timeout
class TestTimeout:
    def test_timeout_marks_game_over(self):
        state = _make_state()
        rng = random.Random(42)
        state = rules.apply_update_tick(state, 10_000, rng)
        assert state.public_state["phase"] == "timeout"
        assert state.is_game_over is True
        assert rules.check_game_over(state) is True

    def test_no_timeout_below_10s(self):
        state = _make_state()
        rng = random.Random(42)
        state = rules.apply_update_tick(state, 9_999, rng)
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
        rng = random.Random(42)
        state = rules.apply_update_tick(state, 0, rng)
        assert state.public_state["phase"] == "waiting_for_move"
        assert state.public_state["round"] == 1


# ------------------------------------------- state update integrity (#8)
class TestStateUpdateIntegrity:
    def test_update_private_state_preserves_existing_keys(self):
        state = GameState(session_id="test", private_state={"p1": {"score": 5, "choice": ""}})
        state.update_private_state("p1", {"choice": "R"})
        assert state.private_state["p1"]["choice"] == "R"
        assert state.private_state["p1"]["score"] == 5  # preserved

    def test_update_private_state_creates_entry_for_new_player(self):
        state = GameState(session_id="test", private_state={})
        state.update_private_state("p1", {"choice": "", "my_score": 0})
        assert state.private_state["p1"] == {"choice": "", "my_score": 0}

    def test_update_public_state_preserves_existing_keys(self):
        state = GameState(session_id="test", public_state={"phase": "waiting_for_move", "round": 3})
        state.update_public_state({"phase": "round_complete"})
        assert state.public_state["phase"] == "round_complete"
        assert state.public_state["round"] == 3  # preserved

    def test_setup_player_state_preserves_scores_on_rejoin(self):
        """setup_player_state must not reset a player's accumulated score."""
        state = _make_state()
        state.private_state["p1"]["my_score"] = 3
        state.private_state["p1"]["opponent_score"] = 1

        from pyslap.models.domain import Player
        player = Player(player_id="p1", name="Alice")
        state = rules.setup_player_state(state, player)

        assert state.private_state["p1"]["my_score"] == 3       # preserved
        assert state.private_state["p1"]["opponent_score"] == 1  # preserved
        assert state.private_state["p1"]["choice"] == ""         # reset

    def test_setup_player_state_initializes_scores_for_new_player(self):
        """setup_player_state must initialize scores to 0 when player has no existing state."""
        state = _make_state(players=["p1"])
        state.private_state.pop("p1", None)  # remove p1 entirely

        from pyslap.models.domain import Player
        player = Player(player_id="p1", name="Alice")
        state = rules.setup_player_state(state, player)

        assert state.private_state["p1"]["my_score"] == 0
        assert state.private_state["p1"]["opponent_score"] == 0

    def test_round_complete_tick_preserves_scores(self):
        """apply_update_tick on round_complete must not erase scores."""
        state = _make_state(phase="round_complete")
        state.private_state["p1"]["my_score"] = 2
        state.private_state["p2"]["my_score"] = 1

        rng = random.Random(42)
        state = rules.apply_update_tick(state, 500, rng)

        assert state.private_state["p1"]["my_score"] == 2  # preserved
        assert state.private_state["p2"]["my_score"] == 1  # preserved
