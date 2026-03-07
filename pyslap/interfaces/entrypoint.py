from abc import ABC, abstractmethod
from typing import Any, Optional

from pyslap.models.domain import GameState


class EntrypointInterface(ABC):
    @abstractmethod
    def start_session(self, game_id: str, player_id: str, player_name: str, custom_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def send_action (self, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any], nonce: int = 0) -> bool:
        pass

    @abstractmethod
    def get_state(self, session_id: str, player_id: str, token: str) -> GameState:
        pass

    @abstractmethod
    def get_data(self, session_id: str, player_id: str, token: str, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        pass