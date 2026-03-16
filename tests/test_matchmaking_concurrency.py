import asyncio
import time
import pytest
from unittest.mock import MagicMock
from pyslap.core.engine import PySlapEngine
from pyslap.models.domain import Player, Role, SessionStatus, GameConfig
from pyslap.interfaces.database import DatabaseInterface
from pyslap.interfaces.scheduler import SchedulerInterface
from pyslap.core.game_rules import GameRules
from games.rps import RpsGameRules
from local.sql_database import SQLiteDatabase
import os

@pytest.mark.asyncio
async def test_matchmaking_concurrency ():
    """
    Simulates multiple players trying to join the SAME matchmaking session.
    Verifies that the CLAIMED status prevents multiple players from attempting
    to mutate the same record simultaneously, leading to linear (successful) joins.
    """
    db_path = "test_matchmaking.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    db = SQLiteDatabase(db_path)
    scheduler = MagicMock(spec=SchedulerInterface)
    games = {"rps": RpsGameRules()}
    engine = PySlapEngine(db, scheduler, games, secret_key="test", external_secret="ext")

    # 1. Setup Game Config
    db.create("game_configs", {
        "id": "rps",
        "game_id": "rps",
        "max_players": 2,
        "update_interval_ms": 1000
    })

    # 2. Register players
    players = []
    for i in range(10):
        p_id = f"p{i}"
        token = engine.security.generate_guest_auth_token()
        players.append((p_id, token))

    # 3. Create one matchmaking session
    # We'll have p0 create it.
    res = engine.create_session("rps", players[0][1], custom_data={"matchmaking": True})
    session_id = res.session_id
    
    # 4. Simulate concurrent joins by p1-p9
    async def join_task (p_id, token):
        # We wrap in a thread because PySlapEngine is synchronous (for now)
        return await asyncio.to_thread(
            engine.create_session, "rps", token, custom_data={"matchmaking": True}
        )

    tasks = [join_task(players[i][0], players[i][1]) for i in range(1, 10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 5. Verification
    # Only ONE player should have joined the original session (since max_players=2).
    # The others should have either created new sessions or joined other newly created ones.
    
    joined_original = 0
    new_sessions = set()
    errors = []

    for r in results:
        if isinstance(r, BaseException):
            errors.append(r)
        elif r.session_id == session_id:
            joined_original += 1
        else:
            new_sessions.add(r.session_id)

    assert not errors, f"Encountered errors: {errors}"
    assert joined_original == 1, f"Expected exactly 1 player to join original session, got {joined_original}"
    
    # Check that we don't have multiple players in the same slot
    state_data = db.read("states", session_id)
    assert state_data != None
    assert len(state_data["slots"]) == 2
    assert len(set(state_data["slots"].values())) == 2
    
    # Cleanup
    pass
