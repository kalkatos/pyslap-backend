import json
import os
import azure.functions as func

# Ensure project root is available for pyslap imports if this is deployed directly
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from typing import Any
from pyslap.core.engine import PySlapEngine
from pyslap.models.domain import GameState
from azure.azure_database import AzureTableDatabase
from azure.azure_scheduler import AzureScheduler
from games.rps import RpsGameRules

# Initialize Services globally for function reuse
db = AzureTableDatabase()
scheduler = AzureScheduler(queue_name="pyslapupdates")

engine = PySlapEngine(
    db=db,
    scheduler=scheduler,
    games_registry={"rps": RpsGameRules()}
)

# Initialize Azure Function App
app = func.FunctionApp()

@app.route(route="start_session", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def start_session(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        game_id = req_body.get('game_id')
        player_id = req_body.get('player_id')
        player_name = req_body.get('player_name')
        
        if not game_id or not player_id or not player_name:
            return func.HttpResponse("Missing parameters", status_code=400)
            
        result = engine.create_session(game_id, player_id, player_name)
        if result:
            return func.HttpResponse(json.dumps(result), mimetype="application/json", status_code=200)
        else:
            return func.HttpResponse("Failed to create session", status_code=400)
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

@app.route(route="send_action", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def send_action(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        session_id = req_body.get('session_id')
        player_id = req_body.get('player_id')
        token = req_body.get('token')
        action_type = req_body.get('action_type')
        payload = req_body.get('payload', {})
        
        if not session_id or not player_id or not token or not action_type:
            return func.HttpResponse("Missing parameters", status_code=400)
            
        success = engine.register_action(session_id, player_id, token, action_type, payload)
        if success:
            return func.HttpResponse(json.dumps({"status": "success"}), mimetype="application/json", status_code=200)
        else:
            return func.HttpResponse(json.dumps({"status": "error", "message": "Failed to register action"}), mimetype="application/json", status_code=400)
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

@app.route(route="get_state", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def get_state(req: func.HttpRequest) -> func.HttpResponse:
    session_id = req.params.get('session_id')
    player_id = req.params.get('player_id')
    token = req.params.get('token')
    
    if not session_id or not player_id or not token:
        return func.HttpResponse("Missing parameters", status_code=400)

    # Reconstruct state fetching logic
    session_data = engine.db.read("sessions", session_id)
    if not session_data:
        return func.HttpResponse("Session not found", status_code=404)
        
    game_id = session_data["game_id"]
    rules = engine.games.get(game_id)
    if not rules:
        return func.HttpResponse("Game rules not found", status_code=500)

    state_data = engine.db.read("states", session_id)
    if not state_data:
        return func.HttpResponse("State not found", status_code=404)
        
    state_data.pop("id", None)
    game_state = GameState(**state_data)
    
    client_state = game_state.to_player_state(player_id)
    return func.HttpResponse(json.dumps(client_state), mimetype="application/json", status_code=200)

@app.route(route="get_data", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def get_data(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        session_id = req_body.get('session_id')
        player_id = req_body.get('player_id')
        token = req_body.get('token')
        collection = req_body.get('collection')
        filters = req_body.get('filters', {})
        
        if not session_id or not collection:
            return func.HttpResponse("Missing parameters", status_code=400)
            
        # Add session_id to filters if it's relevant for the collection
        query_filters = filters.copy()
        if "session_id" not in query_filters:
            query_filters["session_id"] = session_id
            
        data = engine.db.query(collection, query_filters)
        return func.HttpResponse(json.dumps(data), mimetype="application/json", status_code=200)
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

@app.queue_trigger(arg_name="msg", queue_name="pyslapupdates", connection="AZURE_STORAGE_CONNECTION_STRING")
def process_update_queue(msg: func.QueueMessage) -> None:
    try:
        message_body = msg.get_body().decode('utf-8')
        data = json.loads(message_body)
        session_id = data.get("session_id")
        
        if session_id:
            engine.process_update_loop(session_id)
    except Exception as e:
        print(f"Error processing update queue: {e}")
