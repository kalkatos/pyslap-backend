from typing import Any
from pyslap.interfaces.entrypoint import EntrypointInterface
from pyslap.core.engine import PySlapEngine
from pyslap.models.domain import GameState

class LocalEntrypoint(EntrypointInterface):
    """
    A local implementation of EntrypointInterface that directly interacts with PySlapEngine.
    """

    def __init__(self, engine: PySlapEngine):
        self.engine = engine

    def start_session(self, game_id: str, player_id: str, player_name: str) -> dict[str, Any] | None:
        """
        Starts a new session for a player.
        """
        return self.engine.create_session(game_id, player_id, player_name)

    def send_action(self, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any]) -> None:
        """
        Relays the action to the engine's register_action method.
        """
        self.engine.register_action(session_id, player_id, token, action_type, payload)

    def get_state(self, session_id: str, player_id: str, token: str) -> GameState:
        """
        Retrieves the current game state for a specific player.
        """
        # PySlapEngine doesn't have a direct 'get_state' method for a player yet.
        # We need to fetch it from the database and use the game rules to prepare it.
        
        # Load session to verify game rules
        session_data = self.engine.db.read("sessions", session_id)
        if not session_data:
            raise ValueError(f"Session {session_id} not found")
        
        game_id = session_data["game_id"]
        rules = self.engine.games.get(game_id)
        if not rules:
            raise ValueError(f"Game rules for {game_id} not found")

        # Load raw state
        state_data = self.engine.db.read("states", session_id)
        if not state_data:
            raise ValueError(f"State for session {session_id} not found")
        
        # Remove ID if present for dataclass init
        state_data.pop("id", None)
        game_state = GameState(**state_data)

        # Prepare state for client
        return game_state.to_player_state(player_id)

    def get_data(self, session_id: str, player_id: str, token: str, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Queries data from the engine's database with filters.
        """
        # Security check (ensure player belongs to session/has access)
        # For simplicity in local entrypoint, we follow PySlapEngine's pattern of minimal checks here
        # or assuming the token validation happens if needed.
        
        # Add session_id to filters if it's relevant for the collection
        query_filters = filters.copy()
        if "session_id" not in query_filters:
            query_filters["session_id"] = session_id
            
        return self.engine.db.query(collection, query_filters)
