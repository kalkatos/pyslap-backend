import time
from unittest.mock import MagicMock

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
