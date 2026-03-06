from fastapi.testclient import TestClient
from local.app import app, db
import pytest
import os

client = TestClient(app)

@pytest.fixture(autouse=True)
def cleanup_db():
    yield
    # Clean up DB after test
    conn = db._get_connection()
    try:
        conn.execute("DELETE FROM records")
        conn.commit()
    finally:
        conn.close()

def test_start_session():
    db.create("game_configs", {"id": "rps", "update_interval_ms": 1000, "max_lifetime_sec": 3600, "session_timeout_sec": 300})
    
    response = client.post("/session", json={
        "game_id": "rps",
        "player_id": "p1",
        "player_name": "Player 1"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "token" in data
    assert "state" in data
    assert data["state"]["public_state"]["round"] == 1

def test_start_session_unknown_game():
    response = client.post("/session", json={
        "game_id": "unknown_game",
        "player_id": "p1",
        "player_name": "Player 1"
    })
    
    assert response.status_code == 400
    
def test_get_state():
    db.create("game_configs", {"id": "rps", "update_interval_ms": 1000, "max_lifetime_sec": 3600, "session_timeout_sec": 300})
    
    # Start session
    resp1 = client.post("/session", json={
        "game_id": "rps",
        "player_id": "p1",
        "player_name": "Player 1"
    })
    session_data = resp1.json()
    session_id = session_data["session_id"]
    token = session_data["token"]
    
    # Get state
    resp2 = client.get(f"/state?session_id={session_id}&player_id=p1&token={token}")
    assert resp2.status_code == 200
    state_data = resp2.json()
    assert state_data["session_id"] == session_id
    assert state_data["is_game_over"] is False

def test_send_action():
    db.create("game_configs", {"id": "rps", "update_interval_ms": 1000, "max_lifetime_sec": 3600, "session_timeout_sec": 300})
    
    # Start session
    resp1 = client.post("/session", json={
        "game_id": "rps",
        "player_id": "p1",
        "player_name": "Player 1"
    })
    session_data = resp1.json()
    session_id = session_data["session_id"]
    token = session_data["token"]
    
    # Action
    resp2 = client.post("/action", json={
        "session_id": session_id,
        "player_id": "p1",
        "token": token,
        "action_type": "move",
        "payload": {"choice": "R"}
    })
    assert resp2.status_code == 200
    assert resp2.json() == {"status": "success"}

def test_get_data():
    db.create("game_configs", {"id": "rps", "update_interval_ms": 1000, "max_lifetime_sec": 3600, "session_timeout_sec": 300})
    
    # Start session
    resp1 = client.post("/session", json={
        "game_id": "rps",
        "player_id": "p1",
        "player_name": "Player 1"
    })
    session_data = resp1.json()
    session_id = session_data["session_id"]
    token = session_data["token"]
    
    # Get data
    resp2 = client.post("/data", json={
        "session_id": session_id,
        "player_id": "p1",
        "token": token,
        "collection": "sessions",
        "filters": {"id": session_id}
    })
    assert resp2.status_code == 200
    data = resp2.json()["data"]
    assert len(data) == 1
    assert data[0]["game_id"] == "rps"
