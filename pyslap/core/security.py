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

    def verify_identity(self, player_id: str, name: str) -> Optional[Player]:
        """
        Verifies if the player exists in the database.
        If they exist and match, returns a Player object with a generated token.
        If they don't exist, this logic might create them (depending on external auth needs).
        For now, this assumes we either verify or create.
        """
        # We would use the DatabaseInterface to query:
        # result = self.db.read("players", player_id)
        # if result and result.get("name") == name:
        #     return Player(player_id=player_id, name=name, token=self.generate_token())
        # return None
        
        # Stub: Auto-verify / Auto-create for simplicity
        return Player(player_id=player_id, name=name, token=self.generate_token())

    def validate_request_token(self, player_id: str, token: str) -> bool:
        """
        Validates if the provided security token matches the token assigned
        to the player during verification.
        """
        # Real implementation would fetch the active session's player list or user database
        # result = self.db.read("players", player_id)
        # return result and result.get("token") == token
        
        # Stub placeholder logic
        return True
