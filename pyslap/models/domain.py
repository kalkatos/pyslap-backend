from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SessionStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"


@dataclass
class Player:
    """Represents a player in the system."""
    player_id: str
    name: str
    token: Optional[str] = None


@dataclass
class Action:
    """An action taken by a player."""
    player_id: str
    action_type: str
    payload: dict[str, Any]
    timestamp: float


@dataclass
class GameConfig:
    """Configuration specific to a game implementation."""
    game_id: str
    update_interval_ms: int = 500
    max_players: int = 2
    session_timeout_sec: int = 300  # 5 minutes
    max_lifetime_sec: int = 3600    # 1 hour
    custom_settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class GameState:
    """The state of a game."""
    session_id: str
    is_game_over: bool = False
    public_state: dict[str, Any] = field(default_factory=dict)
    private_state: dict[str, dict[str, Any]] = field(default_factory=dict) # player_id -> private state
    last_update_timestamp: float = 0.0

    def to_player_state(self, player_id: str) -> 'GameState':
        new_state: 'GameState' = GameState(**self.__dict__)
        new_state.private_state = self.private_state.get(player_id, {})
        return new_state


@dataclass
class Session:
    """A game session."""
    session_id: str
    game_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    players: dict[str, Player] = field(default_factory=dict)
    created_at: float = 0.0
    last_action_at: float = 0.0
