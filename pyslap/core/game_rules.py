from abc import ABC, abstractmethod
from typing import Any, Optional

from pyslap.models.domain import Action, GameState, Player


class GameRules(ABC):
    """
    Abstract base class for specific game implementations.
    New games should inherit from this class and implement the required methods
    without modifying the core py-slap backend.
    """

    @abstractmethod
    def create_game_state(self, players: list[Player], custom_data: dict[str, Any]) -> GameState:
        """
        Creates the initial game state. for the specific game.
        """
        pass

    @abstractmethod
    def validate_action(self, action: Action, state: GameState) -> bool:
        """
        Validates if an action is legal for the specific game.
        Returns True if the action is valid, False otherwise.
        """
        pass

    @abstractmethod
    def apply_action(self, action: Action, state: GameState) -> GameState:
        """
        Applies a valid action to the GameState, modifying it accordingly.
        Returns the updated GameState.
        """
        pass

    @abstractmethod
    def apply_update_tick(self, state: GameState, delta_ms: int) -> GameState:
        """
        Applies a regular time-based update tick to the game state.
        This allows for games that update passively over time (e.g. physics ticks).
        Returns the updated GameState.
        """
        pass

    @abstractmethod
    def check_game_over(self, state: GameState) -> bool:
        """
        Evaluates the current state to check if the game has reached an end state.
        Should return True if the game is over. The core engine will read this
        and terminate the session if necessary.
        """
        pass

    def get_phase_gates(self) -> set[str]:
        """
        Returns a set of phase names that must be seen by all session
        players before apply_update_tick is allowed to transition them.
        Override in subclasses. Default: no gated phases.
        """
        return set()


