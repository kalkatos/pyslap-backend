from typing import Any, Callable, ParamSpec, TypeVar
from functools import wraps
from pyslap.interfaces.entrypoint import EntrypointInterface
from pyslap.core.engine import PySlapEngine
from pyslap.models.domain import GameState, Role

P = ParamSpec("P")
R = TypeVar("R")

def ensure_role (required_role: Role):
    def decorator (func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper (*args: P.args, **kwargs: P.kwargs) -> R:
            # Extraction of self and token to verify role
            # We assume this is used on methods with (self, session_id, player_id, token, ...)
            if not args:
                 return func(*args, **kwargs)
            
            instance: Any = args[0]
            token: Any = kwargs.get("token")
            
            if token is None and len(args) > 3:
                token = args[3]
            
            if hasattr(instance, "engine") and isinstance(token, str):
                payload = instance.engine.security.get_token_payload(token)
                if not payload or payload.get("role") != required_role.value:
                    raise PermissionError(f"Action requires role {required_role.value}")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


class LocalEntrypoint(EntrypointInterface):
    """
    A local implementation of EntrypointInterface that directly interacts with PySlapEngine.
    """

    def __init__ (self, engine: PySlapEngine):
        self.engine = engine

    def start_session (self, game_id: str, auth_token: str, role: Role = Role.PLAYER, custom_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        Starts a new session for a player using an external auth token.
        """
        return self.engine.create_session(game_id, auth_token, role, custom_data)

    @ensure_role(Role.PLAYER)
    def send_action (self, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any], nonce: int = 0) -> bool:
        """
        Relays the action to the engine's register_action method.
        """
        return self.engine.register_action(session_id, player_id, token, action_type, payload, nonce)

    def get_state (self, session_id: str, player_id: str, token: str) -> GameState:
        """
        Retrieves the current game state for a specific player.
        Phase acknowledgment is handled natively by the engine via the "ack"
        framework action — no implicit ack logic here.
        """
        # Verify the token before serving any data
        if not self.engine.security.validate_request_token(session_id, player_id, token):
            raise PermissionError(f"Invalid token for player {player_id} in session {session_id}")

        # Load raw state
        state_data = self.engine.db.read("states", session_id)
        if not state_data:
            raise ValueError(f"State for session {session_id} not found")

        # Remove ID if present for dataclass init
        state_data.pop("id", None)
        game_state = GameState(**state_data)

        # Prepare state for client
        player_state = game_state.to_player_state(player_id)

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

