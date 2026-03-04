from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class SessionStatus(Enum):
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
    payload: Dict[str, Any]
    timestamp: float


@dataclass
class GameConfig:
    """Configuration specific to a game implementation."""
    game_id: str
    update_interval_ms: int = 500
    max_players: int = 2
    session_timeout_sec: int = 300  # 5 minutes
    max_lifetime_sec: int = 3600    # 1 hour
    custom_settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GameState:
    """The state of a game."""
    session_id: str
    is_game_over: bool = False
    public_state: Dict[str, Any] = field(default_factory=dict)
    private_state: Dict[str, Dict[str, Any]] = field(default_factory=dict) # player_id -> private state
    last_update_timestamp: float = 0.0


@dataclass
class Session:
    """A game session."""
    session_id: str
    game_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    players: Dict[str, Player] = field(default_factory=dict)
    created_at: float = 0.0
    last_action_at: float = 0.0
