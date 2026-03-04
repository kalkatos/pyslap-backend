from abc import ABC, abstractmethod


class SchedulerInterface(ABC):
    """
    Interface exclusively for scheduling the next execution of the update loop.
    Agnostic to platform (e.g., AWS EventBridge, Cloud Functions Pub/Sub, etc.).
    """

    @abstractmethod
    def schedule_next_update(self, session_id: str, delay_ms: int) -> bool:
        """
        Schedules an update loop execution for the given session ID after
        a specified delay in milliseconds (typically >= 500ms).
        Returns True if scheduling was successful.
        """
        pass
