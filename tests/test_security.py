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
    security = SecurityManager(mock_db)
    
    player = security.verify_identity(player_id="p1", name="Alice")
    
    assert player is not None
    assert player.player_id == "p1"
    assert player.name == "Alice"
    assert player.token is not None
    assert len(player.token) == 64


def test_validate_request_token():
    mock_db = MagicMock()
    security = SecurityManager(mock_db)
    
    # Using the stub response
    assert security.validate_request_token("p1", "some-token") is True
