from unittest.mock import MagicMock

from pyslap.core.security import SecurityManager


def test_generate_token():
    mock_db = MagicMock()
    security = SecurityManager(mock_db)
    
    token1 = security.generate_token()
    token2 = security.generate_token()
    
    assert token1 != token2
    assert len(token1) == 64  # secrets.token_hex(32) outputs 64 characters


def test_verify_identity_success():
    mock_db = MagicMock()
    mock_db.read.return_value = {"id": "p1", "name": "Alice"}  # Player exists
    security = SecurityManager(mock_db)
    
    player = security.verify_identity(player_id="p1", name="Alice")
    
    assert player is not None
    assert player.player_id == "p1"
    assert player.name == "Alice"
    assert player.token is not None
    assert len(player.token) == 64


def test_verify_identity_unknown_player():
    mock_db = MagicMock()
    mock_db.read.return_value = None  # Player not found
    security = SecurityManager(mock_db)
    
    player = security.verify_identity(player_id="unknown", name="Alice")
    
    assert player is None


def test_validate_request_token():
    mock_db = MagicMock()
    security = SecurityManager(mock_db)
    
    # Simulate a session where p1 has token "abc123"
    mock_db.read.return_value = {
        "players": {"p1": {"player_id": "p1", "name": "Alice", "token": "abc123"}}
    }
    assert security.validate_request_token("sid_1", "p1", "abc123") is True
    assert security.validate_request_token("sid_1", "p1", "wrong-token") is False
