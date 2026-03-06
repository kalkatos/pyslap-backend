import json
from typing import Callable, Any
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
import datetime

from pyslap.interfaces.scheduler import SchedulerInterface


class CloudTasksScheduler(SchedulerInterface):
    """
    Google Cloud Tasks implementation of SchedulerInterface.
    Schedules an HTTP target task to trigger the update loop endpoint independently.
    """

    def __init__(self, project_id: str, location_id: str, queue_id: str, cloud_function_url: str):
        """
        Initializes the Cloud Task client and configuration for the target endpoint.
        """
        self.project_id = project_id
        self.location_id = location_id
        self.queue_id = queue_id
        self.cloud_function_url = cloud_function_url

        self.client = tasks_v2.CloudTasksClient()
        self.parent = self.client.queue_path(self.project_id, self.location_id, self.queue_id)
        
        self.callback: Callable[[str], Any] | None = None

    def set_callback(self, callback: Callable[[str], Any]) -> None:
        """
        In Cloud Tasks serverless model, the callback runs in another
        execution instance of the HTTP function. Strictly keeping the interface
        signature, but it might just be the logic invoked by the HTTP handler.
        """
        self.callback = callback

    def schedule_next_update(self, session_id: str, delay_ms: int) -> bool:
        """
        Enqueues an HTTP Target task in Cloud Tasks to run after `delay_ms`.
        """
        payload = {"session_id": session_id}
        
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": self.cloud_function_url,
                "headers": {"Content-type": "application/json"},
                "body": json.dumps(payload).encode(),
            }
        }

        # Set the schedule time based on the current time + delay_ms
        if delay_ms > 0:
            d = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(milliseconds=delay_ms)
            timestamp = timestamp_pb2.Timestamp()
            timestamp.FromDatetime(d)
            task["schedule_time"] = timestamp  # type: ignore

        try:
            self.client.create_task(
                request={"parent": self.parent, "task": task}
            )
            return True
        except Exception as e:
            print(f"Failed to schedule task: {e}")
            return False
