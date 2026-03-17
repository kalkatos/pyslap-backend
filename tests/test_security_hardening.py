import time
import pytest
from unittest.mock import MagicMock
from pyslap.core.security import SecurityManager
from pyslap.config import settings

def test_session_token_ttl_expiration():
    mock_db = MagicMock()
    # Set a short TTL for testing
    settings.session_token_ttl = 2
    
    security = SecurityManager(mock_db, secret_key="test_secret_32bytes_min_key_length")
    
    token = security.generate_session_token(player_id="p1", session_id="sid_1")
    
    # Immediately valid
    assert security.validate_request_token("sid_1", "p1", token) is True
    
    # Wait for expiration
    time.sleep(2.5)
    
    # Now invalid
    assert security.validate_request_token("sid_1", "p1", token) is False

def test_security_manager_no_debug_token():
    mock_db = MagicMock()
    security = SecurityManager(mock_db)
    
    # Verify create_debug_external_token is NOT present
    assert not hasattr(security, "create_debug_external_token")
