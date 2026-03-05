import time
import uuid
from typing import Any, Mapping

from dataclasses import asdict
from pyslap.core.security import SecurityManager
from pyslap.core.validator import Validator
from pyslap.core.game_rules import GameRules
from pyslap.interfaces.database import DatabaseInterface
from pyslap.interfaces.scheduler import SchedulerInterface
from pyslap.models.domain import (Action, GameConfig, GameState, Player, Session, SessionStatus)


class PySlapEngine:
    """
    The orchestrator of the PySlap framework.
    Stateless by design to fit within Serverless architectures. All state
    is loaded from the DB, processed, and saved back.
    """
    db: DatabaseInterface
    scheduler: SchedulerInterface
    games: Mapping[str, GameRules]
    validator: Validator
    security: SecurityManager

    def __init__(
            self,
            db: DatabaseInterface,
            scheduler: SchedulerInterface,
            games_registry: Mapping[str, GameRules]
    ):
        self.db = db
        self.scheduler = scheduler
        self.games = games_registry
        self.validator = Validator(db)
        self.security = SecurityManager(db)


    def create_session(self, game_id: str, requester_id: str, requester_name: str) -> dict[str, Any] | None:
        """
        Creates a new session, generates tokens, and schedules the first update.
        """
        if game_id not in self.games:
            return None  # Unknown game
            
        # Verify requester
        player = self.security.verify_identity(requester_id, requester_name)
        if not player:
            return None

        # Fetch Game Configurations
        config_data = self.db.read("game_configs", game_id) or {}
        config = GameConfig(game_id=game_id, **config_data)

        # Create Session Object
        session_id = str(uuid.uuid4())
        current_time = time.time()
        
        session = Session(
            session_id=session_id,
            game_id=game_id,
            status=SessionStatus.ACTIVE,
            players={player.player_id: player},
            created_at=current_time,
            last_action_at=current_time
        )
        
        # Initialize GameState
        game_state = self.games[game_id].create_game_state([player])
        game_state.session_id = session_id
        game_state.last_update_timestamp = current_time

        # Save to database
        session_data = asdict(session)
        session_data["id"] = session_id
        state_data = asdict(game_state)
        state_data["id"] = session_id
        
        self.db.create("sessions", session_data)
        self.db.create("states", state_data)

        # Schedule the first update loop using the interface
        self.scheduler.schedule_next_update(session_id, config.update_interval_ms)

        # Prepare and return initial state for the requester with their specific private state
        client_state = game_state.to_player_state(player.player_id)
        
        return {
            "session_id": session_id,
            "token": player.token,
            "state": client_state
        }


    def register_action(self, session_id: str, player_id: str, token: str, action_type: str, payload: dict[str, Any]) -> bool:
        """
        Registers an action for the next update loop.
        """
        if not self.security.validate_request_token(player_id, token):
            return False

        # Load session to validate
        session_data = self.db.read("sessions", session_id)
        if not session_data:
            return False
            
        session_data.pop("id", None)
        session = Session(**session_data)
        if session.status != SessionStatus.ACTIVE:
            return False

        current_time = time.time()
        
        # Anti-spam check
        if not self.validator.validate_action_rate(session, player_id, current_time):
            return False

        action = Action(
            player_id=player_id, 
            action_type=action_type, 
            payload=payload, 
            timestamp=current_time
        )

        # Let Validator log it via DB
        self.validator.log_action(action)
        
        # Update session `last_action_at` timestamp
        session.last_action_at = current_time
        session_data = asdict(session)
        session_data["id"] = session_id
        self.db.update("sessions", session_id, session_data)

        return True


    def process_update_loop(self, session_id: str) -> None:
        """
        The polling loop executed periodically. Processes pending actions and game state.
        This must be independent of other runs (Serverless requirement).
        """
        current_time = time.time()
        
        # 1. Load Session & Config
        session_data = self.db.read("sessions", session_id)
        if not session_data:
            return
            
        session_data.pop("id", None)
        session = Session(**session_data)
        if session.status != SessionStatus.ACTIVE:
            return

        config_data = self.db.read("game_configs", session.game_id) or {}
        config = GameConfig(game_id=session.game_id, **config_data)

        # 2. Check Session Timeouts
        if self.validator.check_session_lifetime(session, current_time, config.max_lifetime_sec) or \
           self.validator.check_session_timeout(session, current_time, config.session_timeout_sec):
            session.status = SessionStatus.TERMINATED
            session_data = asdict(session)
            session_data["id"] = session_id
            self.db.update("sessions", session_id, session_data)
            return # Exit loop without scheduling next
            
        # 3. Load GameState & Actions
        state_data = self.db.read("states", session_id)
        if not state_data:
            return
        
        state_data.pop("id", None)
        state = GameState(**state_data)
        rules = self.games[session.game_id]
        
        pending_actions = self.db.query("actions", {"session_id": session_id, "processed": False})

        # 4. Apply Updates
        # First, apply regular time-based updates (if any)
        delta_ms = int((current_time - state.last_update_timestamp) * 1000)
        state = rules.apply_update_tick(state, delta_ms)
        state.last_update_timestamp = current_time

        # Second, apply valid player actions
        for raw_act in pending_actions:
            action = Action(
                player_id=raw_act["player_id"],
                action_type=raw_act["action_type"],
                payload=raw_act["payload"],
                timestamp=raw_act["timestamp"]
            )
            if rules.validate_action(action, state):
                state = rules.apply_action(action, state)
            
            # Mark action as processed
            raw_act["processed"] = True
            self.db.update("actions", raw_act["id"], raw_act)

        # 5. Check Game Over
        if rules.check_game_over(state):
            state.is_game_over = True
            session.status = SessionStatus.TERMINATED
            
            session_data = asdict(session)
            session_data["id"] = session_id
            state_data = asdict(state)
            state_data["id"] = session_id
            
            self.db.update("sessions", session_id, session_data)
            self.db.update("states", session_id, state_data)
            return # Exit loop

        # 6. Save State and Reschedule
        state_data = asdict(state)
        state_data["id"] = session_id
        self.db.update("states", session_id, state_data)
        
        # Enforce serverless minimum interval requirement (>=500ms)
        delay_ms = max(config.update_interval_ms, 500)
        self.scheduler.schedule_next_update(session_id, delay_ms)
