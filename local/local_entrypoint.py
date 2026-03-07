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

    def send_action (self, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any]) -> bool:
        """
        Relays the action to the engine's register_action method.
        """
        return self.engine.register_action(session_id, player_id, token, action_type, payload)

    def get_state (self, session_id: str, player_id: str, token: str) -> GameState:
        """
        Retrieves the current game state for a specific player.
        """
        # Verify the token before serving any data
        if not self.engine.security.validate_request_token(session_id, player_id, token):
            raise PermissionError(f"Invalid token for player {player_id} in session {session_id}")

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
        player_state = game_state.to_player_state(player_id)
        
        # Register ack for phase gate if needed
        gated_phases = rules.get_phase_gates()
        current_phase = game_state.public_state.get("phase")
        
        if current_phase in gated_phases and player_id in game_state.phase_ack:
            if not game_state.phase_ack[player_id]:
                game_state.phase_ack[player_id] = True
                
                # Resave state with ack
                from dataclasses import asdict
                state_to_save = asdict(game_state)
                state_to_save["id"] = session_id
                self.engine.db.update("states", session_id, state_to_save)
                
        return player_state

    def get_data (self, session_id: str, player_id: str, token: str, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Queries data from the engine's database with filters.
        """
        # Verify the token before serving any data
        if not self.engine.security.validate_request_token(session_id, player_id, token):
            raise PermissionError(f"Invalid token for player {player_id} in session {session_id}")

        # Add session_id to filters if it's relevant for the collection
        query_filters = filters.copy()
        if "session_id" not in query_filters:
            query_filters["session_id"] = session_id
            
        return self.engine.db.query(collection, query_filters)

