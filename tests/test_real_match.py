import multiprocessing
import time
import pytest
import uvicorn
import httpx
import asyncio
from local.app import app, db
from games.rps_client import run_client

# Setup basic config for tests
def setup_game_config():
    db.create(
        "game_configs",
        {
            "id": "rps",
            "update_interval_ms": 100,
            "max_players": 2,
            "session_timeout_sec": 60,
            "max_lifetime_sec": 300,
            "phase_ack_timeout_sec": 5,
            "min_action_gap_ms": 10,
        },
    )

def run_server():
    """Function to run the FastAPI server in a separate process."""
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

@pytest.fixture(scope="module")
def server_process():
    """Fixture to start and stop the server process."""
    setup_game_config()
    proc = multiprocessing.Process(target=run_server, daemon=True)
    proc.start()
    
    # Wait for server to be ready
    start_time = time.time()
    while time.time() - start_time < 5:
        try:
            with httpx.Client() as client:
                client.get("http://127.0.0.1:8000/docs")
                break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail("Server failed to start on port 8000")
        
    yield proc
    proc.terminate()
    proc.join()

async def mock_input(prompt, phase, round_num, moves):
    """Injected input function for rps_client."""
    if phase == "waiting_for_move":
        # round_num is 1-indexed
        idx = round_num - 1
        if idx < len(moves):
            return moves[idx]
    return "<timeout>"

@pytest.mark.anyio
async def test_full_rps_match (server_process):
    """The main E2E test running two players through a full match using rps_client.py."""
    
    # Player 1: Wins with Rock twice
    p1_config = {
        "base_url": "http://127.0.0.1:8000",
        "player_id": "test_p1",
        "game_id": "rps",
        "matchmaking": True
    }
    p1_moves = ["R", "R"]
    
    # Player 2: Loses with Scissors twice
    p2_config = {
        "base_url": "http://127.0.0.1:8000",
        "player_id": "test_p2",
        "game_id": "rps",
        "matchmaking": True
    }
    p2_moves = ["S", "S"]

    # Start P1 first to ensure they are the session creator (role 'p1')
    p1_task = asyncio.create_task(run_client(p1_config, input_func=lambda p, ph, r: mock_input(p, ph, r, p1_moves)))
    
    # Small delay to ensure P1 is registered as the first player
    await asyncio.sleep(1.0)
    
    p2_task = asyncio.create_task(run_client(p2_config, input_func=lambda p, ph, r: mock_input(p, ph, r, p2_moves)))
    
    p1_final, p2_final = await asyncio.gather(p1_task, p2_task)
    
    assert p1_final is not None, "Player 1 should have finished the game"
    assert p2_final is not None, "Player 2 should have finished the game"
    
    # Assert match result (P1 wins 2-0)
    final_public = p1_final["public_state"]
    assert final_public["phase"] == "game_over"
    
    # Verify scores from P1's perspective
    p1_private = p1_final["private_state"]
    assert p1_private["my_score"] == 2
    assert p1_private["opponent_score"] == 0
    
    # Verify scores from P2's perspective
    p2_private = p2_final["private_state"]
    assert p2_private["my_score"] == 0
    assert p2_private["opponent_score"] == 2
    
    # The winner string might be 'p1' or 'p2' depending on exact join order 
    # but based on our sleep it should be 'p1'. 
    # We assert based on scores which is more fundamental.
