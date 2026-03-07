import secrets
from typing import Optional

from pyslap.interfaces.database import DatabaseInterface
from pyslap.models.domain import Player


class SecurityManager:
    """
    Handles identity verification and secure tokens for requesters.
    Verifies requesters' IDs/names against the database, generates security
    tokens, and checks incoming request tokens.
    """

    def __init__(self, db: DatabaseInterface):
        self.db = db

    def generate_token(self) -> str:
        """Generates a secure, random token for a session requester."""
        return secrets.token_hex(32)

    def verify_identity (self, player_id: str, name: str) -> Optional[Player]:
        """
        Verifies the player exists in the database.
        Returns a Player with a fresh session token if found, or None if the
        player_id is not registered.
        """
        record = self.db.read("players", player_id)
        if not record:
            return None  # Unknown player — reject
        return Player(player_id=player_id, name=name, token=self.generate_token())

    def validate_request_token (self, session_id: str, player_id: str, token: str) -> bool:
        """
        Validates that the token matches the one stored in the session for this player.
        Returns False if the session doesn't exist, the player isn't in it, or the
        token doesn't match.
        """
        session_data = self.db.read("sessions", session_id)
        if not session_data:
            return False
        players = session_data.get("players", {})
        player_data = players.get(player_id)
        if not player_data:
            return False
        expected_token = player_data.get("token") if isinstance(player_data, dict) else getattr(player_data, "token", None)
        return expected_token == token
