import json
from enum import Enum
from dataclasses import dataclass, asdict, field
from typing import Dict

class SessionStatus(Enum):
    ACTIVE = "active"

class SessionStatusStr(str, Enum):
    ACTIVE = "active"

@dataclass
class Player:
    name: str

@dataclass
class Session:
    status: SessionStatus
    players: Dict[str, Player] = field(default_factory=dict)

@dataclass
class SessionStr:
    status: SessionStatusStr
    players: Dict[str, Player] = field(default_factory=dict)

print("--- Standard Enum ---")
try:
    print(json.dumps(SessionStatus.ACTIVE))
except TypeError as e:
    print(f"Caught expected error: {e}")

print("\n--- (str, Enum) ---")
try:
    # In some Python versions, this works because it's a str subclass
    print(f"json.dumps(SessionStatusStr.ACTIVE): {json.dumps(SessionStatusStr.ACTIVE)}")
except TypeError as e:
    print(f"Caught error: {e}")

print("\n--- Dataclass asdict with Standard Enum ---")
s = Session(status=SessionStatus.ACTIVE, players={"p1": Player(name="Alice")})
d = asdict(s)
print(f"asdict outcome: {d}")
try:
    print(json.dumps(d))
except TypeError as e:
    print(f"Caught error: {e}")

print("\n--- Dataclass asdict with (str, Enum) ---")
s2 = SessionStr(status=SessionStatusStr.ACTIVE, players={"p1": Player(name="Alice")})
d2 = asdict(s2)
print(f"asdict outcome: {d2}")
try:
    print(json.dumps(d2))
except TypeError as e:
    print(f"Caught error: {e}")
