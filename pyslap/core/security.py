import time
import jwt
from typing import Optional

from pyslap.interfaces.database import DatabaseInterface
from pyslap.models.domain import Player


class SecurityManager:
    """
    Handles identity verification and secure tokens for requesters.
    Verifies requesters' IDs/names against the database, generates security
    tokens, and checks incoming request tokens.
    """

    def __init__(self, db: DatabaseInterface, secret_key: str = "pyslap_default_secret_key_32_bytes_min"):
        self.db = db
        self.secret_key = secret_key

    def generate_session_token (self, player_id: str, session_id: str) -> str:
        """Generates a signed JWT session token."""
        payload = {
            "player_id": player_id,
            "session_id": session_id,
            "exp": time.time() + 86400  # 24 hours expiration
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def verify_identity (self, player_id: str, name: str) -> Optional[Player]:
        """
        Verifies the player exists in the database.
        Returns a Player without a token (token is generated per-session later).
        Returns None if the player_id is not registered.
        """
        record = self.db.read("players", player_id)
        if not record:
            return None  # Unknown player — reject
        return Player(player_id=player_id, name=name)

    def validate_request_token (self, session_id: str, player_id: str, token: str) -> bool:
        """
        Validates that the token is a valid JWT for this session and player.
        Returns False if the signature is invalid, expired, or data mismatches.
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            if payload.get("player_id") != player_id:
                return False
            if payload.get("session_id") != session_id:
                return False
            return True
        except jwt.PyJWTError:
            return False
