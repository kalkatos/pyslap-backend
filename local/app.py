from dataclasses import asdict
import os
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from pyslap.core.engine import PySlapEngine
from pyslap.models.domain import Role
from local.local_scheduler import LocalScheduler
from local.sql_database import SQLiteDatabase
from local.local_entrypoint import LocalEntrypoint
from games.rps import RpsGameRules

# Initialize components
db = SQLiteDatabase()
db.create("players", {"id": "player1", "name": "Player 1", "token": "fake_token"})
db.create("players", {"id": "player2", "name": "Player 2", "token": "fake_token"})
db.create("players", {"id": "0cc60167-8efe-44a4-afbf-579ae2022f41", "name": "UUID Player 1", "token": "fake_token"})
db.create("players", {"id": "7c931abf-eb13-4154-9b92-6699ee36f88b", "name": "UUID Player 2", "token": "fake_token"})
db.create("players", {"id": "computer", "name": "Computer", "token": "fake_token"})
scheduler = LocalScheduler()

# Register games
games_registry = {
    "rps": RpsGameRules()
}

# Initialize Engine and Entrypoint
secret_key = os.environ.get("PYSLAP_SECRET_KEY")
external_secret = os.environ.get("PYSLAP_EXTERNAL_SECRET")
engine = PySlapEngine(
    db=db, 
    scheduler=scheduler, 
    games_registry=games_registry,
    secret_key=secret_key,
    external_secret=external_secret
)
entrypoint = LocalEntrypoint(engine)

app = FastAPI(title="PYSLAP Local Backend API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler (request: Request, exc: Exception) -> Response:
    return _rate_limit_exceeded_handler(request, exc) # type: ignore


# --- Pydantic Models for Requests ---

class StartSessionRequest(BaseModel):
    game_id: str
    auth_token: str
    role: str = "player"
    custom_data: Dict[str, Any] | None = None

class ActionRequest(BaseModel):
    session_id: str
    player_id: str
    token: str
    action_type: str
    payload: Dict[str, Any]
    nonce: int = 0

class StateRequest(BaseModel):
    session_id: str
    player_id: str
    token: str

class DataRequest(BaseModel):
    session_id: str
    player_id: str
    token: str
    collection: str
    filters: Dict[str, Any]

# --- API Endpoints ---

@app.post("/session")
@limiter.limit("5/minute")
async def start_session (request: Request, req: StartSessionRequest):
    try:
        req_role = Role(req.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role specified.")
        
    try:
        result = entrypoint.start_session(req.game_id, req.auth_token, req_role, req.custom_data)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to start session. Check game_id or player details.")
        return result
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/action")
@limiter.limit("60/minute")
async def send_action (request: Request, req: ActionRequest):
    try:
        success = entrypoint.send_action(req.session_id, req.player_id, req.token, req.action_type, req.payload, req.nonce)
        if success is False:
            raise HTTPException(status_code=403, detail="Action rejected: invalid token, session, or permission.")
        return {"status": "success"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/state")
async def get_state (session_id: str, player_id: str, token: str):
    try:
        state = entrypoint.get_state(session_id, player_id, token)
        return asdict(state)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/data")
async def get_data (req: DataRequest):
    try:
        data = entrypoint.get_data(req.session_id, req.player_id, req.token, req.collection, req.filters)
        return {"data": data}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
