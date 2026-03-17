import time
import jwt
import uuid
from typing import Optional

from pyslap.interfaces.database import DatabaseInterface
from pyslap.models.domain import Player, Role
from pyslap.config import settings


class SecurityManager:
    """
    Handles identity verification and secure tokens for requesters.
    Verifies requesters' IDs/names against the database, generates security
    tokens, and checks incoming request tokens.
    """

    def __init__(self, db: DatabaseInterface, secret_key: str | None = None, external_secret: str | None = None):
        self.db = db
        self.secret_key = secret_key or settings.secret_key
        self.external_secret = external_secret or settings.external_secret

    def generate_session_token (self, player_id: str, session_id: str, role: Role = Role.PLAYER) -> str:
        """Generates a signed JWT session token."""
        payload = {
            "player_id": player_id,
            "session_id": session_id,
            "role": role.value,
            "exp": time.time() + settings.session_token_ttl
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
            
            if not player_id:
                return None
            
            player_id = str(player_id)
            is_guest_token = payload.get("is_guest", False)
            
            # Reject if guest tokens are disabled but the user is presenting one
            if is_guest_token and not settings.guest_allowed:
                return None

            record = self.db.read("players", player_id)
            
            # Check guest TTL
            if record and record.get("is_guest"):
                creation_time = record.get("registered_at", 0)
                if time.time() - creation_time > settings.guest_lifetime_sec:
                    return None  # Guest expired

            if not record:
                # Just-In-Time (JIT) Registration
                # Automatically create unknown players using data from their JWT token
                name = str(payload.get("name") or self._create_guest_name())
                player_data = {
                    "id": player_id,
                    "name": name,
                    "registered_at": time.time(),
                    "is_guest": is_guest_token
                }
                # Use fail_if_exists=True to handle concurrent registration races atomicaly
                created_id = self.db.create("players", player_data, fail_if_exists=True)
                
                if not created_id:
                    # Race: someone else created the player record between our check (line 53) and create.
                    # Re-read the record to ensure consistency.
                    record = self.db.read("players", player_id)
                    if not record:
                        return None  # Should be impossible unless deleted concurrently
                else:
                    record = player_data
            
            # Prevent users that are marked as guests in DB from logging in if guests are disabled
            if record.get("is_guest") and not settings.guest_allowed:
                return None

            name = str(payload.get("name") or record.get("name"))
            final_name = str(record.get("name") or name)
            return Player(player_id=player_id, name=final_name, role=role)
        except jwt.PyJWTError:
            return None

    def generate_guest_auth_token (self) -> str:
        """
        Creates a temporary identity token for a first-time anonymous user.
        Uses external secret to be uniformly verified in verify_identity.
        """
        guest_id = f"{settings.guest_id_prefix}{uuid.uuid4().hex}"
        payload = {
            "player_id": guest_id,
            "name": self._create_guest_name(),
            "is_guest": True,
            "exp": time.time() + settings.guest_lifetime_sec
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

    def _create_guest_name (self) -> str:
        return f"guest_{uuid.uuid4().hex}"
