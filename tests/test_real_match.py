import multiprocessing
import time
import pytest
import uvicorn
import httpx
import asyncio
import jwt
from local.app import app, db
from pyslap.core.security import SecurityManager

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
                # Just any endpoint to check if up
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

async def player_join(client: httpx.AsyncClient, player_id: str):
    """Simulates a player joining matchmaking."""
    # Create debug token
    token = jwt.encode(
        {"player_id": player_id, "name": f"TestPlayer_{player_id}", "exp": time.time() + 3600},
        "pyslap_default_external_secret_32_bytes_min",
        algorithm="HS256"
    )
    
    resp = await client.post("http://127.0.0.1:8000/session", json={
        "game_id": "rps",
        "auth_token": token,
        "custom_data": {"matchmaking": True}
    })
    assert resp.status_code == 200
    return resp.json()

async def play_game(player_id: str, session_id: str, player_token: str, moves: list[str]):
    """Simulates a player playing through a list of moves."""
    move_idx = 0
    client_nonce = 0
    last_version = -1
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            # Poll for state
            resp = await client.get("http://127.0.0.1:8000/state", params={
                "session_id": session_id,
                "player_id": player_id,
                "token": player_token
            })
            assert resp.status_code == 200
            state = resp.json()
            
            curr_version = state.get("state_version", 0)
            if curr_version == last_version:
                await asyncio.sleep(0.1)
                continue
            
            last_version = curr_version
            ps = state["public_state"]
            phase = ps.get("phase")
            
            if phase == "waiting_for_move":
                if move_idx < len(moves):
                    client_nonce += 1
                    move_resp = await client.post("http://127.0.0.1:8000/action", json={
                        "session_id": session_id,
                        "player_id": player_id,
                        "token": player_token,
                        "action_type": "move",
                        "payload": {"choice": moves[move_idx]},
                        "nonce": client_nonce
                    })
                    assert move_resp.status_code == 200
                    move_idx += 1
            
            elif phase == "round_complete":
                # Acknowledge gated phase
                ack_resp = await client.post("http://127.0.0.1:8000/action", json={
                    "session_id": session_id,
                    "player_id": player_id,
                    "token": player_token,
                    "action_type": "ack",
                    "payload": {},
                    "nonce": 0
                })
                # Engine might have already transitioned if other player acked first
                # so we don't strictly assert 200 here if it's already past the phase
            
            elif phase == "game_over":
                return state
            
            await asyncio.sleep(0.1)

@pytest.mark.anyio
async def test_full_rps_match (server_process):
    """The main E2E test running two players through a full match."""
    async with httpx.AsyncClient() as client:
        # 1. Players join
        p1_res = await player_join(client, "p1")
        p2_res = await player_join(client, "p2")
        
        session_id = p1_res["session_id"]
        assert p2_res["session_id"] == session_id
        
        # 2. Run both players concurrently
        # Moves: 
        # Round 1: P1=R, P2=S -> P1 wins
        # Round 2: P1=R, P2=S -> P1 wins
        # Result: P1 wins 2-0
        p1_task = asyncio.create_task(play_game("p1", session_id, p1_res["token"], ["R", "R"]))
        p2_task = asyncio.create_task(play_game("p2", session_id, p2_res["token"], ["S", "S"]))
        
        p1_final, p2_final = await asyncio.gather(p1_task, p2_task)
        
        # 3. Assert match result
        final_public = p1_final["public_state"]
        assert final_public["phase"] == "game_over"
        assert final_public["winner"] == "p1"
        assert final_public["p1_score"] == 2
        assert final_public["p2_score"] == 0
