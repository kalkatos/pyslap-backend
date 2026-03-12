import time
import uuid
from typing import Any, Mapping

from dataclasses import asdict
from pyslap.core.security import SecurityManager
from pyslap.core.validator import Validator
from pyslap.core.game_rules import GameRules
from pyslap.interfaces.database import DatabaseInterface
from pyslap.interfaces.scheduler import SchedulerInterface
from pyslap.models.domain import Action, GameConfig, GameState, Session, SessionStatus, Role


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

    MINIMUM_UPDATE_INTERVAL_MS = 100

    def __init__(
        self,
        db: DatabaseInterface,
        scheduler: SchedulerInterface,
        games_registry: Mapping[str, GameRules],
        secret_key: str | None = None,
        external_secret: str | None = None,
    ):
        self.db = db
        self.scheduler = scheduler
        self.games = games_registry
        self.validator = Validator(db)
        
        # Initialize Security Manager with provided keys, or let it use defaults
        security_kwargs: dict[str, Any] = {"db": db}
        if secret_key:
            security_kwargs["secret_key"] = secret_key
        if external_secret:
            security_kwargs["external_secret"] = external_secret
            
        self.security = SecurityManager(**security_kwargs)
        self.scheduler.set_callback(self.process_update_loop)
        self._cleanup_old_records()

    def _cleanup_old_records(self, max_age_sec: int = 5 * 3600) -> None:
        """Deletes sessions older than max_age_sec (default 5 hours) and their related data."""
        cutoff = time.time() - max_age_sec
        old_sessions = [
            s
            for s in self.db.query("sessions", {})
            if s.get("created_at", float("inf")) < cutoff
        ]
        for session in old_sessions:
            session_id = session["id"]

            # Delete all actions tied to this session
            old_actions = self.db.query("actions", {"session_id": session_id})
            for action in old_actions:
                self.db.delete("actions", action["id"])

            # Delete state and session records
            self.db.delete("states", session_id)
            self.db.delete("sessions", session_id)

    def create_session(
        self, game_id: str, auth_token: str, role: Role = Role.PLAYER, custom_data: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """
        Creates a new session, generates tokens, and schedules the first update.
        """
        if game_id not in self.games:
            return None  # Unknown game

        # Verify requester using external auth token
        player = self.security.verify_identity(auth_token, role)
        if not player:
            raise PermissionError("Player not registered or invalid auth token, please register first")

        # Fetch Game Configurations
        config_data = self.db.read("game_configs", game_id) or {}
        config_data.pop("id", None)
        config = GameConfig(game_id=game_id, **config_data)

        # Handle Matchmaking Wait-and-Join
        if custom_data and custom_data.get("matchmaking"):
            query_filters = {"game_id": game_id, "status": SessionStatus.MATCHMAKING}
            
            # If a specific lobby is requested, filter by it. 
            # Otherwise, only match with sessions that have NO lobby_id (general matchmaking).
            join_lobby_id = custom_data.get("join_lobby")
            query_filters["lobby_id"] = join_lobby_id

            waiting_sessions = self.db.query("sessions", query_filters)
            
            for session_data in waiting_sessions:
                s_id = session_data["id"]
                session_data.pop("id", None)
                session = Session(**session_data)
                
                if player.player_id in session.players:
                    continue  # Player is already in this session
                
                player.token = self.security.generate_session_token(player.player_id, s_id, role)
                session.players[player.player_id] = player
                
                state_data = self.db.read("states", s_id)
                if not state_data:
                    continue
                state_data.pop("id", None)
                state = GameState(**state_data)

                # Assign sticky slot if not already assigned
                if player.player_id not in state.slots.values():
                    slot_id = f"slot_{len(state.slots)}"
                    state.slots[slot_id] = player.player_id
                
                if len(session.players) >= config.max_players:
                    session.status = SessionStatus.ACTIVE
                
                updated_session_data = asdict(session)
                updated_session_data["id"] = s_id
                self.db.update("sessions", s_id, updated_session_data)
                
                # Record phase before game-rules touch it
                original_phase = state.public_state.get("phase")

                state = self.games[game_id].setup_player_state(state, player)

                # Engine-owned version bump on phase change (mirrors process_update_loop)
                new_phase = state.public_state.get("phase")
                if new_phase != original_phase:
                    state.state_version += 1
                    state.phase_ack = {p: False for p in session.players.keys()}
                    state.phase_ack_since = time.time()
                
                updated_state_data = asdict(state)
                updated_state_data["id"] = s_id
                self.db.update("states", s_id, updated_state_data)
                
                client_state = state.to_player_state(player.player_id)
                return {"session_id": s_id, "token": player.token, "state": client_state, "lobby_id": session.lobby_id}

        # Create Session Object
        session_id = str(uuid.uuid4())
        current_time = time.time()

        # Generate a stateless session token for the player
        player.token = self.security.generate_session_token(player.player_id, session_id, role)

        initial_status = SessionStatus.MATCHMAKING if (custom_data and custom_data.get("matchmaking")) else SessionStatus.ACTIVE

        lobby_id = None
        if custom_data and custom_data.get("create_lobby"):
            import string
            import random
            # Generate a 6-letter uppercase ID (QOEMDU)
            letters = string.ascii_uppercase
            lobby_id = ''.join(random.choice(letters) for i in range(6))
            # Automatically force matchmaking phase so others can join this lobby
            initial_status = SessionStatus.MATCHMAKING

        session = Session(
            session_id=session_id,
            game_id=game_id,
            status=initial_status,
            players={player.player_id: player},
            custom_data=custom_data or {},
            created_at=current_time,
            last_action_at=current_time,
            lobby_id=lobby_id,
        )

        # Initialize GameState
        game_state = self.games[game_id].create_game_state([player], custom_data or {})
        game_state.session_id = session_id
        game_state.last_update_timestamp = current_time
        game_state.phase_ack = {}
        
        # Assign first sticky slot
        game_state.slots["slot_0"] = player.player_id

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

        return {"session_id": session_id, "token": player.token, "state": client_state, "lobby_id": lobby_id}

    # Framework-reserved action types handled natively by the engine.
    FRAMEWORK_ACTIONS = frozenset({"ack"})

    def register_action(
        self,
        session_id: str,
        player_id: str,
        token: str,
        action_type: str,
        payload: dict[str, Any],
        nonce: int = 0
    ) -> bool:
        """
        Registers an action for the next update loop.
        Framework actions (e.g. "ack") are handled immediately by the engine
        and never forwarded to game rules.
        """
        if not self.security.validate_request_token(session_id, player_id, token):
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

        # --- Native framework action: ack ---
        if action_type == "ack":
            return self._handle_ack(session_id, session, player_id, current_time)

        action = Action(
            session_id=session_id,
            player_id=player_id,
            action_type=action_type,
            payload=payload,
            timestamp=current_time,
            nonce=nonce
        )

        # Let Validator log it via DB
        self.validator.log_action(action)

        # Update session `last_action_at` timestamp
        session.last_action_at = current_time
        session_data = asdict(session)
        session_data["id"] = session_id
        self.db.update("sessions", session_id, session_data)

        return True

    def _handle_ack(
        self,
        session_id: str,
        session: Session,
        player_id: str,
        current_time: float,
    ) -> bool:
        """
        Handles the native 'ack' framework action.
        Marks the player as having acknowledged the current gated phase.
        Takes effect immediately (no queuing) so the gate can clear on the next tick.
        """
        rules = self.games.get(session.game_id)
        if not rules:
            return False

        gated_phases = rules.get_phase_gates()
        if not gated_phases:
            return False  # Game has no gated phases

        state_data = self.db.read("states", session_id)
        if not state_data:
            return False

        state_data.pop("id", None)
        state = GameState(**state_data)

        current_phase = state.public_state.get("phase")
        if current_phase not in gated_phases:
            return False  # Not currently in a gated phase

        if player_id not in state.phase_ack:
            return False  # Player not part of the ack set

        if state.phase_ack[player_id]:
            return True  # Already acked, idempotent success

        state.phase_ack[player_id] = True

        state_data = asdict(state)
        state_data["id"] = session_id
        self.db.update("states", session_id, state_data)

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
        if session.status not in (SessionStatus.ACTIVE, SessionStatus.MATCHMAKING):
            return

        config_data = self.db.read("game_configs", session.game_id) or {}
        config_data.pop("id", None)
        config = GameConfig(game_id=session.game_id, **config_data)

        # 2. Check Session Timeouts
        if self.validator.check_session_lifetime(
            session, current_time, config.max_lifetime_sec
        ) or self.validator.check_session_timeout(
            session, current_time, config.session_timeout_sec
        ):
            session.status = SessionStatus.TERMINATED
            session_data = asdict(session)
            session_data["id"] = session_id
            self.db.update("sessions", session_id, session_data)
            return  # Exit loop without scheduling next

        # 3. Load GameState & Actions
        state_data = self.db.read("states", session_id)
        if not state_data:
            return

        state_data.pop("id", None)
        state = GameState(**state_data)
        rules = self.games[session.game_id]

        pending_actions = self.db.query(
            "actions", {"session_id": session_id, "processed": False}
        )

        # 4. Apply Updates

        # Track phase for version bumping
        original_phase = state.public_state.get("phase")

        # Phase Gate Check
        gated_phases = rules.get_phase_gates()
        current_phase = state.public_state.get("phase")
        skip_tick = False

        if current_phase in gated_phases:
            # Check if all actual players (excluding AI added later) have acked
            session_players = set([p for p in session.players.keys()])
            unacked_players = [
                p for p in session_players if not state.phase_ack.get(p, False)
            ]

            if unacked_players:
                # Check for timeout
                if current_time - state.phase_ack_since >= config.phase_ack_timeout_sec:
                    # Force-clear the gate
                    pass  # We proceed with the tick
                else:
                    skip_tick = True

        # First, apply regular time-based updates (if any) and not gated
        if not skip_tick:
            delta_ms = int((current_time - state.last_update_timestamp) * 1000)
            state = rules.apply_update_tick(state, delta_ms)
            state.last_update_timestamp = current_time

        # Second, apply valid player actions
        for raw_act in pending_actions:
            action = Action(
                session_id=session_id,
                player_id=raw_act["player_id"],
                action_type=raw_act["action_type"],
                payload=raw_act["payload"],
                timestamp=raw_act["timestamp"],
                nonce=raw_act.get("nonce", 0)
            )
            
            # Check nonce before applying
            if self.validator.validate_action_nonce(state, action.player_id, action.nonce):
                if rules.validate_action(action, state):
                    state = rules.apply_action(action, state)
                    # Update local state nonce to prevent replays
                    state.last_nonces[action.player_id] = action.nonce

            # Mark action as processed
            raw_act["processed"] = True
            self.db.update("actions", raw_act["id"], raw_act)

        # Version Bump & Ack Reset only when the phase changed.
        # Partial actions (e.g. one of two players moved) and internal timer changes
        # do NOT bump the version — only a phase transition does.
        new_phase = state.public_state.get("phase")
        if new_phase != original_phase:
            state.state_version += 1
            # Reset acks for session players
            state.phase_ack = {p: False for p in session.players.keys()}
            state.phase_ack_since = current_time

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
            return  # Exit loop

        # 6. Save State and Reschedule
        # Only save if the phase changed (prevents overwriting concurrent phase_ack updates)
        if not skip_tick or new_phase != original_phase:
            state_data = asdict(state)
            state_data["id"] = session_id
            self.db.update("states", session_id, state_data)

        # Enforce serverless minimum interval requirement (>=500ms)
        delay_ms = max(config.update_interval_ms, self.MINIMUM_UPDATE_INTERVAL_MS)
        self.scheduler.schedule_next_update(session_id, delay_ms)
