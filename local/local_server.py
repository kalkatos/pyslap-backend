import asyncio
from typing import Callable, Awaitable, Optional

from pyslap.interfaces.scheduler import SchedulerInterface

class LocalScheduler(SchedulerInterface):
    """
    A local implementation of SchedulerInterface that simply awaits
    0.5s using asyncio before executing the next update.
    """
    
    def __init__(self, update_callback: Optional[Callable[[str], Awaitable[None]]] = None):
        """
        :param update_callback: An async function `async def update_callback(session_id: str)`
                                that executes the actual game loop/update logic.
        """
        self.update_callback = update_callback

    def schedule_next_update(self, session_id: str, delay_ms: int) -> bool:
        """
        Schedules the next update by creating an asyncio task that waits 0.5 seconds
        and then calls the update callback.
        """
        asyncio.create_task(self._wait_and_update(session_id))
        return True

    async def _wait_and_update(self, session_id: str):
        # Simply await 0.5s as requested for the local server
        await asyncio.sleep(0.5)
        
        callback = self.update_callback
        if callback:
            # Execute the next update
            await callback(session_id)
