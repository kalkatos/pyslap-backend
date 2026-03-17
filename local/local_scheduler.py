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
        self._tasks: dict[str, asyncio.Task] = {}

    def set_callback (self, callback: Callable[[str], Any]) -> None:
        self.update_callback = callback

    def schedule_next_update (self, session_id: str, delay_ms: int) -> bool:
        """
        Schedules the next update by creating an asyncio task that waits
        and then calls the update callback. Ensures any previous task
        for the same session is cancelled.
        """
        self.cancel_update(session_id)
        task = asyncio.create_task(self._wait_and_update(session_id, delay_ms))
        self._tasks[session_id] = task
        # Safe cleanup when task finishes
        task.add_done_callback(lambda t: self._tasks.pop(session_id, None) if self._tasks.get(session_id) == t else None)
        return True

    def cancel_update (self, session_id: str) -> bool:
        """
        Cancels any pending update for the given session ID.
        """
        task = self._tasks.pop(session_id, None)
        if task:
            task.cancel()
            return True
        return False

    def is_scheduled (self, session_id: str) -> bool:
        """
        Checks if an update is currently scheduled for the given session ID.
        """
        return session_id in self._tasks

    async def _wait_and_update (self, session_id: str, delay_ms: int):
        await asyncio.sleep(delay_ms / 1000)
        callback = self.update_callback
        if callback:
            res = callback(session_id)
            if inspect.isawaitable(res):
                await res
