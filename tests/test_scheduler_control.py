import asyncio
import pytest
import time
from unittest.mock import MagicMock
from local.local_scheduler import LocalScheduler
from local.sql_database import SQLiteDatabase
from pyslap.core.engine import PySlapEngine
from games.rps import RpsGameRules

@pytest.mark.asyncio
async def test_scheduler_cancellation ():
    scheduler = LocalScheduler()
    session_id = "test_session"
    invoked = False

    def callback (sid: str):
        nonlocal invoked
        invoked = True

    scheduler.set_callback(callback)
    
    # Schedule an update for 100ms
    scheduler.schedule_next_update(session_id, 100)
    assert scheduler.is_scheduled(session_id) is True
    
    # Cancel it immediately
    assert scheduler.cancel_update(session_id) is True
    assert scheduler.is_scheduled(session_id) is False
    
    # Wait 200ms to be sure
    await asyncio.sleep(0.2)
    assert invoked is False

@pytest.mark.asyncio
async def test_scheduler_auto_cancel_on_reschedule ():
    scheduler = LocalScheduler()
    session_id = "test_session"
    invoked_count = 0

    def callback (sid: str):
        nonlocal invoked_count
        invoked_count += 1

    scheduler.set_callback(callback)
    
    # Schedule first update for 200ms
    scheduler.schedule_next_update(session_id, 200)
    
    # Reschedule immediately for 100ms
    scheduler.schedule_next_update(session_id, 100)
    
    # Wait 300ms
    await asyncio.sleep(0.3)
    
    # Should only be invoked once (the second one)
    assert invoked_count == 1

from pyslap.models.domain import Player, Role

@pytest.mark.asyncio
async def test_scheduler_cleanup_cancellation ():
    # Setup engine with in-memory DB
    db = SQLiteDatabase(":memory:")
    scheduler = LocalScheduler()
    engine = PySlapEngine(db, scheduler, {"rps": RpsGameRules()})
    
    # Pass security checks
    player = Player(player_id="p1", name="P1", role=Role.PLAYER)
    engine.security.verify_identity = MagicMock(return_value=player)
    engine.security.generate_session_token = MagicMock(return_value="t1")
    
    # Create a session (schedules an update)
    resp = engine.create_session("rps", "token1")
    s_id = resp.session_id
    
    assert scheduler.is_scheduled(s_id) is True
    
    # Manually backdate the session so it gets cleaned up
    session_data = db.read("sessions", s_id)
    session_data["created_at"] = time.time() - 36000 # 10 hours ago
    db.update("sessions", s_id, session_data)
    
    # Run cleanup
    engine.cleanup_old_records(max_age_sec=3600)
    
    # Verify it was cancelled in the scheduler
    assert scheduler.is_scheduled(s_id) is False
