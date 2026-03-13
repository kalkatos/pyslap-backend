import time
import threading
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import random

from pyslap.core.engine import PySlapEngine
from pyslap.core.game_rules import GameRules
from pyslap.models.domain import Action, GameState, SessionStatus, Player


# --- Dummy Game Rules for Testing ---
class DummyGame(GameRules):
    def create_game_state (self, players: list[Player], custom_data: dict[str, Any]) -> GameState:
        return GameState(session_id="", public_state={"phase": "waiting"}, private_state={})

    def validate_action (self, action: Action, state: GameState) -> bool:
        return True

    def apply_action (self, action: Action, state: GameState, rng: random.Random) -> GameState:
        return state

    def apply_update_tick (self, state: GameState, delta_ms: int, rng: random.Random) -> GameState:
        state.public_state["ticks"] = state.public_state.get("ticks", 0) + 1
        return state

    def check_game_over (self, state: GameState) -> bool:
        return False

    def prepare_state (self, state: GameState, player_id: str, recent_actions: list) -> Dict[str, Any]:
        return {"public": state.public_state, "private": {}}


def _make_mock_db (session_id="sid_1", game_id="dummy", current_time=None):
    """Creates a mock DB with lock-aware side effects for loop protection tests."""
    if current_time is None:
        current_time = time.time()

    locks = {}

    def mock_read (coll, doc_id):
        if coll == "locks":
            return locks.get(doc_id)
        if coll == "sessions":
            return {
                "session_id": session_id,
                "game_id": game_id,
                "status": SessionStatus.ACTIVE,
                "players": {"p1": {"player_id": "p1", "name": "Alice"}},
                "custom_data": {},
                "created_at": current_time,
                "last_action_at": current_time,
            }
        if coll == "game_configs":
            return {"update_interval_ms": 500}
        if coll == "states":
            return {
                "session_id": session_id,
                "last_update_timestamp": current_time - 0.5,
                "public_state": {"phase": "waiting", "ticks": 0},
                "private_state": {},
            }
        return None

    def mock_create (coll, data):
        if coll == "locks":
            locks[data["id"]] = dict(data)
        return data.get("id", "mock_id")

    def mock_update (coll, doc_id, data, expected_version=None):
        if coll == "locks":
            existing = locks.get(doc_id)
            if existing is None:
                return False
            if expected_version is not None and existing.get("version") != expected_version:
                return False
            locks[doc_id] = dict(data)
            return True
        return True

    def mock_delete (coll, doc_id):
        if coll == "locks":
            return locks.pop(doc_id, None) is not None
        return True

    mock_db = MagicMock()
    mock_db.read.side_effect = mock_read
    mock_db.create.side_effect = mock_create
    mock_db.update.side_effect = mock_update
    mock_db.delete.side_effect = mock_delete
    mock_db.query.return_value = []

    return mock_db, locks


# --- Test Cases ---


def test_loop_acquires_and_releases_lock ():
    """Verify the update loop creates a lock before processing and deletes it after."""
    mock_db, locks = _make_mock_db()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    session_id = "sid_1"
    engine.process_update_loop(session_id)

    # Lock should have been created (via create call on "locks" collection)
    lock_creates = [c for c in mock_db.create.call_args_list if c[0][0] == "locks"]
    assert len(lock_creates) == 1

    # Lock should have been released (via delete call on "locks" collection)
    lock_deletes = [c for c in mock_db.delete.call_args_list if c[0][0] == "locks"]
    assert len(lock_deletes) == 1

    # After release, the locks dict should be empty
    assert len(locks) == 0


def test_loop_skipped_when_lock_held ():
    """If another instance holds an active lock, the loop should skip entirely."""
    mock_db, locks = _make_mock_db()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    session_id = "sid_1"
    lock_id = f"loop_{session_id}"

    # Pre-insert an active lock held by another instance
    locks[lock_id] = {
        "id": lock_id,
        "session_id": session_id,
        "holder_id": "other-instance-id",
        "expires_at": time.time() + 30.0,  # Not expired
        "version": 0,
    }

    engine.process_update_loop(session_id)

    # State should NOT have been updated (loop was skipped)
    state_updates = [c for c in mock_db.update.call_args_list if c[0][0] == "states"]
    assert len(state_updates) == 0

    # The existing lock should remain untouched
    assert locks[lock_id]["holder_id"] == "other-instance-id"


def test_expired_lock_can_be_taken_over ():
    """An expired lock should be reclaimable by a new instance via CAS."""
    mock_db, locks = _make_mock_db()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    session_id = "sid_1"
    lock_id = f"loop_{session_id}"

    # Pre-insert an EXPIRED lock
    locks[lock_id] = {
        "id": lock_id,
        "session_id": session_id,
        "holder_id": "dead-instance",
        "expires_at": time.time() - 10.0,  # Expired 10 seconds ago
        "version": 5,
    }

    engine.process_update_loop(session_id)

    # The loop should have processed (state updated)
    state_updates = [c for c in mock_db.update.call_args_list if c[0][0] == "states"]
    assert len(state_updates) == 1

    # Lock should have been released after processing
    assert len(locks) == 0


def test_expired_lock_cas_failure_skips_loop ():
    """If CAS fails when taking over an expired lock (another instance beat us), skip."""
    mock_db, locks = _make_mock_db()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    session_id = "sid_1"
    lock_id = f"loop_{session_id}"

    # Pre-insert an expired lock with version 5
    locks[lock_id] = {
        "id": lock_id,
        "session_id": session_id,
        "holder_id": "dead-instance",
        "expires_at": time.time() - 10.0,
        "version": 5,
    }

    # Override update to simulate CAS failure on locks (another instance won)
    original_update = mock_db.update.side_effect

    def cas_failing_update (coll, doc_id, data, expected_version=None):
        if coll == "locks":
            return False  # Simulate CAS failure
        return original_update(coll, doc_id, data, expected_version=expected_version)

    mock_db.update.side_effect = cas_failing_update

    engine.process_update_loop(session_id)

    # State should NOT have been updated (lock not acquired)
    state_updates = [c for c in mock_db.update.call_args_list if c[0][0] == "states"]
    assert len(state_updates) == 0


def test_lock_released_even_on_exception ():
    """The lock must be released even if the update loop raises an exception."""
    mock_db, locks = _make_mock_db()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    session_id = "sid_1"

    # Make _execute_update_loop raise an exception
    with patch.object(engine, "_execute_update_loop", side_effect=RuntimeError("boom")):
        try:
            engine.process_update_loop(session_id)
        except RuntimeError:
            pass

    # Lock should still have been released despite the exception
    assert len(locks) == 0


def test_lock_version_increments_on_takeover ():
    """When taking over an expired lock, the version must increment for CAS safety."""
    mock_db, locks = _make_mock_db()
    mock_scheduler = MagicMock()
    games = {"dummy": DummyGame()}
    engine = PySlapEngine(db=mock_db, scheduler=mock_scheduler, games_registry=games)

    session_id = "sid_1"
    lock_id = f"loop_{session_id}"

    # Pre-insert an expired lock at version 3
    locks[lock_id] = {
        "id": lock_id,
        "session_id": session_id,
        "holder_id": "dead-instance",
        "expires_at": time.time() - 5.0,
        "version": 3,
    }

    # Capture the CAS update call to verify version bump
    update_calls = []
    original_update = mock_db.update.side_effect

    def tracking_update (coll, doc_id, data, expected_version=None):
        if coll == "locks":
            update_calls.append({
                "data": dict(data),
                "expected_version": expected_version,
            })
        return original_update(coll, doc_id, data, expected_version=expected_version)

    mock_db.update.side_effect = tracking_update

    engine.process_update_loop(session_id)

    # The CAS update should have used expected_version=3 and set version=4
    assert len(update_calls) >= 1
    lock_update = update_calls[0]
    assert lock_update["expected_version"] == 3
    assert lock_update["data"]["version"] == 4


def test_concurrent_loops_only_one_processes ():
    """Simulate concurrent update loop invocations — only one should process."""
    from local.sql_database import SQLiteDatabase
    import tempfile
    import os

    # Use a real SQLite database to test actual concurrency
    db_path = tempfile.mktemp(suffix=".db")
    db = SQLiteDatabase(db_path)

    try:
        mock_scheduler = MagicMock()
        games = {"dummy": DummyGame()}
        engine = PySlapEngine(db=db, scheduler=mock_scheduler, games_registry=games)

        session_id = "concurrent_test"
        current_time = time.time()

        # Seed the database with session and state data
        db.create("sessions", {
            "id": session_id,
            "session_id": session_id,
            "game_id": "dummy",
            "status": SessionStatus.ACTIVE,
            "players": {"p1": {"player_id": "p1", "name": "Alice", "role": "player", "token": None}},
            "custom_data": {},
            "created_at": current_time,
            "last_action_at": current_time,
            "lobby_id": None,
            "version": 0,
        })
        db.create("states", {
            "id": session_id,
            "session_id": session_id,
            "is_game_over": False,
            "state_version": 0,
            "phase_ack": {},
            "phase_ack_since": 0.0,
            "public_state": {"phase": "waiting", "ticks": 0},
            "private_state": {},
            "slots": {},
            "last_nonces": {},
            "last_update_timestamp": current_time - 0.5,
            "random_seed": 42,
            "version": 0,
        })
        db.create("game_configs", {
            "id": "dummy",
            "update_interval_ms": 500,
        })

        results = {"processed": 0, "skipped": 0}
        results_lock = threading.Lock()

        original_execute = engine._execute_update_loop

        def counting_execute (sid):
            with results_lock:
                results["processed"] += 1
            # Add a small delay to increase the window for contention
            time.sleep(0.05)
            original_execute(sid)

        engine._execute_update_loop = counting_execute

        # Launch multiple concurrent update loop invocations
        threads = []
        for _ in range(5):
            t = threading.Thread(target=engine.process_update_loop, args=(session_id,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Exactly one thread should have processed the update
        assert results["processed"] == 1

        # Verify the state was updated exactly once (ticks went from 0 to 1)
        state = db.read("states", session_id)
        assert state["public_state"]["ticks"] == 1

    finally:
        db.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)
