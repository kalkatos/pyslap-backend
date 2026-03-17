import time
import jwt
from pyslap.config import settings

def create_debug_external_token (player_id: str, name: str, external_secret: str | None = None) -> str:
    """Helper to create a valid external auth token for local testing."""
    secret = external_secret or settings.external_secret
    payload = {
        "player_id": player_id,
        "name": name,
        "exp": time.time() + 86400
    }
    return jwt.encode(payload, secret, algorithm="HS256")
