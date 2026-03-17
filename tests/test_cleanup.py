import time
from unittest.mock import MagicMock

from pyslap.core.engine import PySlapEngine
from pyslap.core.game_rules import GameRules
from pyslap.models.domain import Action, GameState, Player
from local.sql_database import SQLiteDatabase

import random
from typing import Any, Dict


# --- Dummy Game Rules for Testing ---
class DummyGame(GameRules):
    def create_game_state(self, players: list[Player], custom_data: dict[str, Any]) -> GameState:
        return GameState(session_id="", public_state={"phase": "waiting"}, private_state={})

    def validate_action(self, action: Action, state: GameState) -> bool:
        return True

    def apply_action(self, action: Action, state: GameState, rng: random.Random) -> GameState:
        return state

    def apply_update_tick(self, state: GameState, delta_ms: int, rng: random.Random) -> GameState:
        return state

    def check_game_over(self, state: GameState) -> bool:
        return False

    def prepare_state(self, state: GameState, player_id: str, recent_actions: list) -> Dict[str, Any]:
        return {"public": state.public_state, "private": {}}


class TestCleanupNotCalledOnInit:
    """Verify that _cleanup_old_records is no longer invoked during __init__."""

    def test_init_does_not_call_cleanup(self):
        mock_db = MagicMock()
        mock_scheduler = MagicMock()
        games = {"dummy": DummyGame()}

        engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

        # query should never have been called (cleanup would have called db.query("sessions", {}))
        mock_db.query.assert_not_called()
        mock_db.delete_by_filter.assert_not_called()


class TestCleanupOldRecords:
    """Verify that cleanup_old_records works correctly as a standalone operation."""

    def test_cleanup_removes_old_sessions_and_related_data(self):
        mock_db = MagicMock()
        mock_scheduler = MagicMock()
        games = {"dummy": DummyGame()}

        engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

        # Simulate delete_by_filter returning old sessions, then actions
        old_session = {"id": "old_session_1", "created_at": 1000.0, "game_id": "dummy"}

        def mock_delete_by_filter(collection, filters):
            if collection == "sessions":
                return [old_session]
            if collection == "actions":
                return [{"id": "act1"}, {"id": "act2"}]
            return []

        mock_db.delete_by_filter.side_effect = mock_delete_by_filter

        result = engine.cleanup_old_records()

        assert result == 1

        # Verify sessions were cleaned via delete_by_filter with comparison operator
        sessions_call = mock_db.delete_by_filter.call_args_list[0]
        assert sessions_call[0][0] == "sessions"
        assert "created_at__lt" in sessions_call[0][1]

        # Verify total calls to delete_by_filter (1 for sessions + 4 related types)
        assert mock_db.delete_by_filter.call_count == 5

        # Verify specific batch filters for related data
        # Note: filters use __in for session IDs
        calls = {call.args[0]: call.args[1] for call in mock_db.delete_by_filter.call_args_list}
        assert calls["actions"] == {"session_id__in": ["old_session_1"]}
        assert calls["rate_limits"] == {"session_id__in": ["old_session_1"]}
        assert calls["states"] == {"id__in": ["old_session_1"]}
        assert calls["locks"] == {"session_id__in": ["old_session_1"]}

        # Individual delete should never be called now
        mock_db.delete.assert_not_called()

    def test_cleanup_returns_zero_when_nothing_to_clean(self):
        mock_db = MagicMock()
        mock_scheduler = MagicMock()
        games = {"dummy": DummyGame()}

        engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)
        mock_db.delete_by_filter.return_value = []

        result = engine.cleanup_old_records()

        assert result == 0
        mock_db.delete.assert_not_called()

    def test_cleanup_handles_multiple_old_sessions(self):
        mock_db = MagicMock()
        mock_scheduler = MagicMock()
        games = {"dummy": DummyGame()}

        engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

        old_sessions = [
            {"id": "old_1", "created_at": 100.0},
            {"id": "old_2", "created_at": 200.0},
            {"id": "old_3", "created_at": 300.0},
        ]

        call_count = [0]

        def mock_delete_by_filter(collection, filters):
            if collection == "sessions":
                return old_sessions
            return []  # No actions for these sessions

        mock_db.delete_by_filter.side_effect = mock_delete_by_filter

        result = engine.cleanup_old_records()

        assert result == 3
        # Verify total calls to delete_by_filter
        assert mock_db.delete_by_filter.call_count == 5

        # Verify that all 3 IDs were passed in the batch filters
        expected_ids = ["old_1", "old_2", "old_3"]
        calls = {call.args[0]: call.args[1] for call in mock_db.delete_by_filter.call_args_list}
        assert calls["states"] == {"id__in": expected_ids}
        
        # Individual delete should never be called
        assert mock_db.delete.call_count == 0


class TestSQLiteDeleteByFilter:
    """Integration tests for SQLiteDatabase.delete_by_filter with server-side filtering."""

    def _make_db(self):
        db = SQLiteDatabase(":memory:")
        return db

    def test_delete_by_exact_match(self):
        db = self._make_db()
        db.create("actions", {"id": "a1", "session_id": "s1", "type": "move"})
        db.create("actions", {"id": "a2", "session_id": "s1", "type": "chat"})
        db.create("actions", {"id": "a3", "session_id": "s2", "type": "move"})

        deleted = db.delete_by_filter("actions", {"session_id": "s1"})

        assert len(deleted) == 2
        assert {d["id"] for d in deleted} == {"a1", "a2"}

        # Verify only s2 action remains
        remaining = db.query("actions", {})
        assert len(remaining) == 1
        assert remaining[0]["id"] == "a3"

    def test_delete_by_lt_operator(self):
        db = self._make_db()
        now = time.time()
        db.create("sessions", {"id": "old", "created_at": now - 7200})
        db.create("sessions", {"id": "new", "created_at": now})

        cutoff = now - 3600
        deleted = db.delete_by_filter("sessions", {"created_at__lt": cutoff})

        assert len(deleted) == 1
        assert deleted[0]["id"] == "old"

        remaining = db.query("sessions", {})
        assert len(remaining) == 1
        assert remaining[0]["id"] == "new"

    def test_delete_by_gt_operator(self):
        db = self._make_db()
        db.create("items", {"id": "low", "score": 10})
        db.create("items", {"id": "high", "score": 90})

        deleted = db.delete_by_filter("items", {"score__gt": 50})

        assert len(deleted) == 1
        assert deleted[0]["id"] == "high"

    def test_delete_by_combined_filters(self):
        db = self._make_db()
        now = time.time()
        db.create("sessions", {"id": "s1", "game_id": "rps", "created_at": now - 7200})
        db.create("sessions", {"id": "s2", "game_id": "rps", "created_at": now})
        db.create("sessions", {"id": "s3", "game_id": "chess", "created_at": now - 7200})

        cutoff = now - 3600
        deleted = db.delete_by_filter("sessions", {"game_id": "rps", "created_at__lt": cutoff})

        assert len(deleted) == 1
        assert deleted[0]["id"] == "s1"

    def test_delete_from_nonexistent_collection(self):
        db = self._make_db()
        deleted = db.delete_by_filter("nonexistent", {"field": "value"})
        assert deleted == []

    def test_delete_with_no_matches(self):
        db = self._make_db()
        db.create("items", {"id": "i1", "value": 100})

        deleted = db.delete_by_filter("items", {"value__lt": 50})

        assert deleted == []
        remaining = db.query("items", {})
        assert len(remaining) == 1


class TestCleanupIntegration:
    """End-to-end test using real SQLiteDatabase."""

    def test_full_cleanup_flow(self):
        db = SQLiteDatabase(":memory:")
        mock_scheduler = MagicMock()
        games = {"dummy": DummyGame()}

        engine = PySlapEngine(db=db, scheduler=mock_scheduler, games_registry=games)

        now = time.time()

        # Create an old session with actions and state
        db.create("sessions", {"id": "old_s", "created_at": now - 20000, "game_id": "dummy", "status": "ACTIVE"})
        db.create("states", {"id": "old_s", "session_id": "old_s", "public_state": {}})
        db.create("actions", {"id": "old_a1", "session_id": "old_s", "type": "move"})
        db.create("actions", {"id": "old_a2", "session_id": "old_s", "type": "move"})

        # Create a recent session with actions and state
        db.create("sessions", {"id": "new_s", "created_at": now, "game_id": "dummy", "status": "ACTIVE"})
        db.create("states", {"id": "new_s", "session_id": "new_s", "public_state": {}})
        db.create("actions", {"id": "new_a1", "session_id": "new_s", "type": "move"})

        # Run cleanup
        cleaned = engine.cleanup_old_records()

        assert cleaned == 1

        # Old session data is gone
        assert db.read("sessions", "old_s") is None
        assert db.read("states", "old_s") is None
        assert db.query("actions", {"session_id": "old_s"}) == []

        # New session data is intact
        assert db.read("sessions", "new_s") is not None
        assert db.read("states", "new_s") is not None
        assert len(db.query("actions", {"session_id": "new_s"})) == 1
