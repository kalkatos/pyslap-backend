from typing import Any

from pyslap.core.engine import PySlapEngine
from pyslap.interfaces.entrypoint import EntrypointInterface
from pyslap.models.domain import GameState


class GCPEntrypoint(EntrypointInterface):
    """
    Google Cloud Platform entrypoint implementation.
    Acts as the conduit between GCP Cloud Functions HTTP handlers and the PySlap engine.
    """

    def __init__(self, engine: PySlapEngine):
        """
        Initializes the entrypoint with a configured PySlapEngine.
        """
        self.engine = engine

    def start_session(self, game_id: str, player_id: str, player_name: str) -> dict[str, Any] | None:
        """
        Starts a new game session.
        Returns a dictionary with session_id, token, and other connection details,
        or None if the operation failed.
        """
        return self.engine.create_session(game_id, player_id, player_name)

    def send_action(self, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any]) -> None:
        """
        Validates the user token and submits an action to the engine.
        """
        self.engine.register_action(session_id, player_id, token, action_type, payload)

    def get_state(self, session_id: str, player_id: str, token: str) -> GameState:
        """
        Validates the user token and retrieves the current game state visible to them.
        """
        session_data = self.engine.db.read("sessions", session_id)
        if not session_data:
            raise ValueError(f"Session {session_id} not found")

        state_data = self.engine.db.read("states", session_id)
        if not state_data:
            raise ValueError(f"State for session {session_id} not found")

        state_data.pop("id", None)
        game_state = GameState(**state_data)

        # Basic security check
        if not self.engine.security.validate_request_token(player_id, token):
             raise ValueError("Unauthorized player token.")

        return game_state.to_player_state(player_id)

    def get_data(self, session_id: str, player_id: str, token: str, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Exposes queries for additional data, validating the user as necessary.
        """
        if not self.engine.security.validate_request_token(player_id, token):
             raise ValueError("Unauthorized player token.")

        query_filters = filters.copy()
        if "session_id" not in query_filters:
            query_filters["session_id"] = session_id
            
        return self.engine.db.query(collection, query_filters)

    def trigger_update_loop(self, session_id: str) -> None:
        """
        Target endpoint for the Cloud Tasks scheduler to invoke the update loop.
        """
        self.engine.process_update_loop(session_id)
