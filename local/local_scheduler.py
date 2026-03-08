import asyncio
import inspect
from typing import Callable, Any

from pyslap.interfaces.scheduler import SchedulerInterface

class LocalScheduler(SchedulerInterface):
    """
    A local implementation of SchedulerInterface that simply awaits
    using asyncio before executing the next update.
    """

    def __init__ (self):
        self.update_callback = None

    def set_callback (self, callback: Callable[[str], Any]) -> None:
        self.update_callback = callback

    def schedule_next_update (self, session_id: str, delay_ms: int) -> bool:
        """
        Schedules the next update by creating an asyncio task that waits 0.5 seconds
        and then calls the update callback.
        """
        asyncio.create_task(self._wait_and_update(session_id, delay_ms))
        return True

    async def _wait_and_update (self, session_id: str, delay_ms: int):
        await asyncio.sleep(delay_ms / 1000)
        callback = self.update_callback
        if callback:
            res = callback(session_id)
            if inspect.isawaitable(res):
                await res
