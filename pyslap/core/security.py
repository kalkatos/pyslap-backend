import time
import jwt
from typing import Optional

from pyslap.interfaces.database import DatabaseInterface
from pyslap.models.domain import Player, Role


class SecurityManager:
    """
    Handles identity verification and secure tokens for requesters.
    Verifies requesters' IDs/names against the database, generates security
    tokens, and checks incoming request tokens.
    """

    def __init__(self, db: DatabaseInterface, secret_key: str = "pyslap_default_secret_key_32_bytes_min", external_secret: str = "pyslap_default_external_secret_32_bytes_min"):
        self.db = db
        self.secret_key = secret_key
        self.external_secret = external_secret

    def generate_session_token (self, player_id: str, session_id: str, role: Role = Role.PLAYER) -> str:
        """Generates a signed JWT session token."""
        payload = {
            "player_id": player_id,
            "session_id": session_id,
            "role": role.value,
            "exp": time.time() + 86400  # 24 hours expiration
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def verify_identity (self, auth_token: str, role: Role = Role.PLAYER) -> Optional[Player]:
        """
        Verifies the player exists using an external auth_token (JWT).
        Returns a Player without a PySlap session token.
        Returns None if the auth_token is invalid or player_id is not registered.
        """
        try:
            payload = jwt.decode(auth_token, self.external_secret, algorithms=["HS256"])
            player_id = payload.get("player_id")
            name = payload.get("name", player_id)
            
            if not player_id:
                return None
                
            record = self.db.read("players", player_id)
            if not record:
                return None  # Unknown player — reject
            
            final_name = record.get("name", name)
            return Player(player_id=player_id, name=final_name, role=role)
        except jwt.PyJWTError:
            return None

    def create_debug_external_token (self, player_id: str, name: str) -> str:
        """Helper to create a valid external auth token for local testing."""
        payload = {
            "player_id": player_id,
            "name": name,
            "exp": time.time() + 86400
        }
        return jwt.encode(payload, self.external_secret, algorithm="HS256")

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

    def get_token_payload (self, token: str) -> Optional[dict]:
        """
        Extracts and verifies the JWT payload.
        """
        try:
            return jwt.decode(token, self.secret_key, algorithms=["HS256"])
        except jwt.PyJWTError:
            return None
