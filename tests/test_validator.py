import time
from unittest.mock import MagicMock, call

from pyslap.core.validator import Validator
from pyslap.models.domain import Action, Session, SessionStatus


def test_validator_check_session_timeout():
    # Setup
    mock_db = MagicMock()
    validator = Validator(mock_db)
    
    current_time = time.time()
    session = Session(
        session_id="test-session",
        game_id="game1",
        status=SessionStatus.ACTIVE,
        created_at=current_time - 1000,
        last_action_at=current_time - 600 # Last action was 10 minutes ago
    )
    
    # Execute
    # Check if timed out with 300sec (5min) limit
    is_timed_out = validator.check_session_timeout(session, current_time, timeout_sec=300)
    
    # Assert
    assert is_timed_out is True
    
    # Execute again with larger limit
    is_timed_out_long = validator.check_session_timeout(session, current_time, timeout_sec=1000)
    assert is_timed_out_long is False


def test_validator_check_session_lifetime():
    mock_db = MagicMock()
    validator = Validator(mock_db)
    
    current_time = time.time()
    session = Session(
        session_id="test-session",
        game_id="game1",
        created_at=current_time - 4000, # Created over an hour ago
        last_action_at=current_time
    )
    
    # Maximum lifetime of 3600 seconds
    assert validator.check_session_lifetime(session, current_time, max_lifetime_sec=3600) is True


def test_validator_log_action_success():
    mock_db = MagicMock()
    validator = Validator(mock_db)
    
    action = Action(
        session_id="test-session",
        player_id="player1",
        action_type="move",
        payload={"x": 1, "y": 2},
        timestamp=12345.0
    )
    
    result = validator.log_action(action)
    
    assert result is True
    mock_db.create.assert_called_once()
    args, kwargs = mock_db.create.call_args
    assert args[0] == "actions"
    assert args[1]["player_id"] == "player1"


def test_validate_action_rate_allows_first_action():
    """First action from a player should always be allowed (no prior record)."""
    mock_db = MagicMock()
    mock_db.read.return_value = None  # No existing rate limit record
    validator = Validator(mock_db)

    session = Session(session_id="s1", game_id="game1")
    result = validator.validate_action_rate(session, "p1", time.time())

    assert result is True
    mock_db.read.assert_called_once_with("rate_limits", "s1:p1")


def test_validate_action_rate_blocks_rapid_action():
    """Action within min_gap_ms of the last one should be blocked."""
    mock_db = MagicMock()
    current_time = time.time()

    # Last action was 50ms ago
    mock_db.read.return_value = {
        "id": "s1:p1",
        "session_id": "s1",
        "player_id": "p1",
        "last_action_at": current_time - 0.050,
    }
    validator = Validator(mock_db)

    session = Session(session_id="s1", game_id="game1")
    result = validator.validate_action_rate(session, "p1", current_time, min_gap_ms=200)

    assert result is False


def test_validate_action_rate_allows_after_gap():
    """Action after min_gap_ms has elapsed should be allowed."""
    mock_db = MagicMock()
    current_time = time.time()

    # Last action was 300ms ago
    mock_db.read.return_value = {
        "id": "s1:p1",
        "session_id": "s1",
        "player_id": "p1",
        "last_action_at": current_time - 0.300,
    }
    validator = Validator(mock_db)

    session = Session(session_id="s1", game_id="game1")
    result = validator.validate_action_rate(session, "p1", current_time, min_gap_ms=200)

    assert result is True


def test_validate_action_rate_per_player_isolation():
    """Rate limiting should be per-player — one player's spam shouldn't block another."""
    mock_db = MagicMock()
    current_time = time.time()
    validator = Validator(mock_db)
    session = Session(session_id="s1", game_id="game1")

    # p1 has a recent action, p2 has none
    def mock_read(collection, record_id):
        if record_id == "s1:p1":
            return {"last_action_at": current_time - 0.050}  # 50ms ago
        return None  # p2 has no record

    mock_db.read.side_effect = mock_read

    assert validator.validate_action_rate(session, "p1", current_time) is False
    assert validator.validate_action_rate(session, "p2", current_time) is True


def test_record_action_rate_creates_new_record():
    """First call should create a new rate limit record."""
    mock_db = MagicMock()
    mock_db.read.return_value = None
    validator = Validator(mock_db)

    current_time = time.time()
    validator.record_action_rate("s1", "p1", current_time)

    mock_db.create.assert_called_once_with("rate_limits", {
        "id": "s1:p1",
        "session_id": "s1",
        "player_id": "p1",
        "last_action_at": current_time,
    })


def test_record_action_rate_updates_existing_record():
    """Subsequent calls should update the existing record."""
    mock_db = MagicMock()
    mock_db.read.return_value = {"id": "s1:p1", "last_action_at": 100.0}
    validator = Validator(mock_db)

    current_time = time.time()
    validator.record_action_rate("s1", "p1", current_time)

    mock_db.update.assert_called_once_with("rate_limits", "s1:p1", {
        "id": "s1:p1",
        "session_id": "s1",
        "player_id": "p1",
        "last_action_at": current_time,
    })
