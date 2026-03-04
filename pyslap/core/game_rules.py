from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from pyslap.models.domain import Action, GameState, Player


class GameRules(ABC):
    """
    Abstract base class for specific game implementations.
    New games should inherit from this class and implement the required methods
    without modifying the core py-slap backend.
    """

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

    @abstractmethod
    def prepare_state(self, state: GameState, player_id: str, recent_actions: List[Action]) -> Dict[str, Any]:
        """
        Generates the state presentation for a specific requester.
        This must merge the `public_state` variable, which is sent to all,
        and the `private_state[player_id]` which is sent only to the owner.
        `recent_actions` contains the actions processed in the most recent update tick.
        Returns a dictionary representing what the player should see.
        """
        pass
