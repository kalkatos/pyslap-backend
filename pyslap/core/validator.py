import time
from typing import Optional

from pyslap.interfaces.database import DatabaseInterface
from pyslap.models.domain import Action, Session


class Validator:
    """
    Core framework validator. Handles business logic validation prior to
    database persistence. This includes player identity checks, anti-spam
    mechanisms, and action rate limiting.
    """

    def __init__(self, db: DatabaseInterface):
        self.db = db

    def validate_action_rate(self, session: Session, player_id: str, current_time: float, min_gap_ms: int = 200) -> bool:
        """
        Validates if the player is allowed to perform an action.
        Prevents action spamming based on the difference between current_time
        and the last recorded action time in the session.
        """
        # In a real implementation we would fetch the specific player's last action timestamp
        # For simplicity, we assume Session.last_action_at holds the latest overall action
        # but a robust anti-spam would track per-player timestamps.
        
        # We simulate a check:
        # if (current_time - player.last_action_at_ms) < min_gap_ms: return False
        
        return True # Stub implementation

    def log_action(self, action: Action, collection: str = "actions") -> bool:
        """
        Logs a validated action to the database via the DatabaseInterface.
        """
        try:
            action_data = {
                "session_id": action.session_id,
                "player_id": action.player_id,
                "action_type": action.action_type,
                "payload": action.payload,
                "timestamp": action.timestamp,
                "processed": False
            }
            self.db.create(collection, action_data)
            return True
        except Exception:
            # Proper logging should go here.
            return False

    def check_session_timeout(self, session: Session, current_time: float, timeout_sec: int) -> bool:
        """
        Checks if the session has timed out due to inactivity.
        Returns True if the session has timed out.
        """
        return (current_time - session.last_action_at) > timeout_sec

    def check_session_lifetime(self, session: Session, current_time: float, max_lifetime_sec: int) -> bool:
        """
        Checks if the session has exceeded its maximum absolute lifetime.
        Returns True if the session must be terminated immediately.
        """
        return (current_time - session.created_at) > max_lifetime_sec
