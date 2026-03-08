from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SessionStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"
    MATCHMAKING = "matchmaking"


class Role(str, Enum):
    PLAYER = "player"
    SPECTATOR = "spectator"
    ADMIN = "admin"


@dataclass
class Player:
    """Represents a player in the system."""
    player_id: str
    name: str
    role: Role = Role.PLAYER
    token: Optional[str] = None


@dataclass
class Action:
    """An action taken by a player."""
    session_id: str
    player_id: str
    action_type: str
    payload: dict[str, Any]
    timestamp: float
    nonce: int = 0


@dataclass
class GameConfig:
    """Configuration specific to a game implementation."""
    game_id: str
    update_interval_ms: int = 0
    max_players: int = 2
    session_timeout_sec: int = 300  # 5 minutes
    max_lifetime_sec: int = 3600    # 1 hour
    phase_ack_timeout_sec: int = 10 # max seconds to wait for all players to ack a gated phase
    custom_settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class GameState:
    """The state of a game."""
    session_id: str
    is_game_over: bool = False
    state_version: int = 0
    phase_ack: dict[str, bool] = field(default_factory=dict)  # player_id -> acked
    phase_ack_since: float = 0.0  # timestamp when the gated phase started
    public_state: dict[str, Any] = field(default_factory=dict)
    private_state: dict[str, dict[str, Any]] = field(default_factory=dict) # player_id -> private state
    last_nonces: dict[str, int] = field(default_factory=dict) # player_id -> last accepted nonce
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
    custom_data: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    last_action_at: float = 0.0
