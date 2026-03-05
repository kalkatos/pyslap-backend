from abc import ABC, abstractmethod
from typing import Callable, Any


class SchedulerInterface(ABC):
    """
    Interface exclusively for scheduling the next execution of the update loop.
    Agnostic to platform (e.g., AWS EventBridge, Cloud Functions Pub/Sub, etc.).
    """

    @abstractmethod
    def set_callback(self, callback: Callable[[str], Any]) -> None:
        """
        Sets the callback to be invoked when a scheduled update is due.
        """
        pass

    @abstractmethod
    def schedule_next_update(self, session_id: str, delay_ms: int) -> bool:
        """
        Schedules an update loop execution for the given session ID after
        a specified delay in milliseconds (typically >= 500ms).
        Returns True if scheduling was successful.
        """
        pass
