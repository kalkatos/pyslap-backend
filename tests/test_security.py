import jwt
from unittest.mock import MagicMock

from pyslap.core.security import SecurityManager
from pyslap.models.domain import Role


def test_generate_session_token():
    mock_db = MagicMock()
    security = SecurityManager(mock_db, secret_key="test_secret_32bytes_min_key_length")
    
    token = security.generate_session_token(player_id="p1", session_id="sid_1")
    
    payload = jwt.decode(token, "test_secret_32bytes_min_key_length", algorithms=["HS256"])
    assert payload["player_id"] == "p1"
    assert payload["session_id"] == "sid_1"
    assert "exp" in payload


def test_verify_identity_success():
    mock_db = MagicMock()
    mock_db.read.return_value = {"id": "p1", "name": "Alice"}  # Player exists
    security = SecurityManager(mock_db)
    
    auth_token = security.create_debug_external_token("p1", "Alice")
    player = security.verify_identity(auth_token)
    
    assert player is not None
    assert player.player_id == "p1"
    assert player.name == "Alice"
    assert player.token is None  # Token is not generated here anymore


def test_verify_identity_unknown_player():
    mock_db = MagicMock()
    mock_db.read.return_value = None  # Player not found initially
    security = SecurityManager(mock_db)
    
    auth_token = security.create_debug_external_token("unknown", "Alice")
    player = security.verify_identity(auth_token)
    
    # Should automatically create player (JIT)
    assert player is not None
    assert player.player_id == "unknown"
    assert player.name == "Alice"
    
    # Verify DB create was called correctly
    assert mock_db.create.call_count == 1
    args, kwargs = mock_db.create.call_args
    assert args[0] == "players"
    assert args[1]["id"] == "unknown"
    assert args[1]["name"] == "Alice"
    assert "registered_at" in args[1]


def test_validate_request_token():
    mock_db = MagicMock()
    security = SecurityManager(mock_db, secret_key="test_secret_32bytes_min_key_length")
    
    # Generate a valid token for player 'p1' in session 'sid_1'
    valid_token = security.generate_session_token(player_id="p1", session_id="sid_1")
    
    assert security.validate_request_token("sid_1", "p1", valid_token) is True
    assert security.validate_request_token("sid_1", "wrong_player", valid_token) is False
    assert security.validate_request_token("wrong_session", "p1", valid_token) is False
    assert security.validate_request_token("sid_1", "p1", "invalid.jwt.token") is False


def test_generate_and_decode_token_with_role():
    mock_db = MagicMock()
    security = SecurityManager(mock_db, secret_key="test_secret_32bytes_min_key_length")
    
    token = security.generate_session_token(player_id="p1", session_id="sid_1", role=Role.SPECTATOR)
    
    payload = security.get_token_payload(token)
    assert payload is not None
    assert payload["player_id"] == "p1"
    assert payload["session_id"] == "sid_1"
    assert payload["role"] == "spectator"
