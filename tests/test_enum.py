import json
from enum import Enum

class SessionStatus(str, Enum):
    MATCHMAKING = "matchmaking"

data = {"status": SessionStatus.MATCHMAKING}
try:
    print(f"Serialized: {json.dumps(data)}")
except Exception as e:
    print(f"Error: {e}")
