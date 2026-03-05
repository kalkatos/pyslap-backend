import os
import json
from typing import Callable, Any, Optional

from azure.storage.queue import QueueClient, BinaryBase64EncodePolicy, BinaryBase64DecodePolicy
from pyslap.interfaces.scheduler import SchedulerInterface

class AzureScheduler(SchedulerInterface):
    """
    Azure Queue Storage implementation of SchedulerInterface.
    Uses message visibility timeout to delay the execution of the update loop.
    """
    
    def __init__(self, connection_string: Optional[str] = None, queue_name: str = "pyslapupdates"):
        if not connection_string:
            connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            if not connection_string:
                raise ValueError("AZURE_STORAGE_CONNECTION_STRING is required in environment variables.")
                
        # Queue names must be all lowercase, alphanumeric, and hyphens (but not starting/ending with hyphens)
        self.queue_client = QueueClient.from_connection_string(
            conn_str=connection_string,
            queue_name=queue_name,
            message_encode_policy=BinaryBase64EncodePolicy(),
            message_decode_policy=BinaryBase64DecodePolicy()
        )
        try:
            self.queue_client.create_queue()
        except Exception:
            pass
            
        self.update_callback = None

    def set_callback(self, callback: Callable[[str], Any]) -> None:
        """
        The callback is registered but for Azure, the actual execution is 
        triggered by the Azure Function Queue trigger binding. We store it here 
        if the entrypoint wants to pull it explicitly.
        """
        self.update_callback = callback

    def schedule_next_update(self, session_id: str, delay_ms: int) -> bool:
        """
        Enqueues a message with visibility timeout equal to delay_ms.
        """
        message = json.dumps({"session_id": session_id}).encode('utf-8')
        visibility_timeout = max(0, int(delay_ms / 1000.0))  # seconds
        
        try:
            self.queue_client.send_message(
                message, 
                visibility_timeout=visibility_timeout
            )
            return True
        except Exception as e:
            print(f"Failed to schedule update for {session_id}: {e}")
            return False
