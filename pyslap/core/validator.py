import time
from typing import Optional

from pyslap.interfaces.database import DatabaseInterface
from pyslap.models.domain import Action, Session, GameState


class Validator:
    """
    Core framework validator. Handles business logic validation prior to
    database persistence. This includes player identity checks, anti-spam
    mechanisms, and action rate limiting.
    """

    def __init__(self, db: DatabaseInterface):
        self.db = db

    def check_and_record_rate_limit (self, session_id: str, player_id: str, current_time: float, min_gap_ms: int = 200) -> bool:
        """
        Atomically checks if the player is allowed to perform an action and
        records the timestamp if successful.
        
        Returns True if the action is allowed and recorded, False if blocked.
        """
        rate_limit_id = f"{session_id}:{player_id}"
        record = {
            "id": rate_limit_id,
            "session_id": session_id,
            "player_id": player_id,
            "last_action_at": current_time,
        }

        # 1. Try to create the record if it doesn't exist (first action)
        # fail_if_exists=True ensures only one concurrent caller succeeds.
        created_id = self.db.create("rate_limits", record, fail_if_exists=True)
        if created_id:
            return True

        # 2. If it exists, attempt atomic conditional update
        # last_action_at__lte = current_time - min_gap_ms/1000
        cutoff = current_time - (min_gap_ms / 1000.0)
        
        return self.db.conditional_update(
            "rate_limits", 
            rate_limit_id, 
            record, 
            {"last_action_at__lte": cutoff}
        )

    def validate_action_rate(self, session: Session, player_id: str, current_time: float, min_gap_ms: int = 200) -> bool:
        """
        [DEPRECATED] Use check_and_record_rate_limit instead.
        """
        rate_limit_id = f"{session.session_id}:{player_id}"
        record = self.db.read("rate_limits", rate_limit_id)

        if record is None:
            return True

        last_action_at = record.get("last_action_at", 0.0)
        elapsed_ms = (current_time - last_action_at) * 1000

        return elapsed_ms >= min_gap_ms

    def record_action_rate(self, session_id: str, player_id: str, timestamp: float) -> None:
        """
        [DEPRECATED] Use check_and_record_rate_limit instead.
        """
        rate_limit_id = f"{session_id}:{player_id}"
        record = {
            "id": rate_limit_id,
            "session_id": session_id,
            "player_id": player_id,
            "last_action_at": timestamp,
        }
        existing = self.db.read("rate_limits", rate_limit_id)
        if existing is None:
            self.db.create("rate_limits", record)
        else:
            self.db.update("rate_limits", rate_limit_id, record)

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
                "nonce": getattr(action, "nonce", 0),
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

    def validate_action_nonce(self, state: GameState, player_id: str, incoming_nonce: int) -> bool:
        """
        Validates the sequence nonce of an incoming action.
        Prevents replay attacks and out-of-order execution.
        """
        expected_nonce = state.last_nonces.get(player_id, 0) + 1
        return incoming_nonce == expected_nonce
