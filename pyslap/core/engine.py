import copy
import random
import time
import uuid
import hashlib
import string
from typing import Any, Mapping

from dataclasses import asdict
from pyslap.core.security import SecurityManager
from pyslap.core.validator import Validator
from pyslap.core.game_rules import GameRules
from pyslap.interfaces.database import DatabaseInterface
from pyslap.interfaces.scheduler import SchedulerInterface
from pyslap.models.domain import Action, GameConfig, GameState, Session, SessionStatus, Role, SessionResponse, Player


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
    DEFAULT_LOOP_LEASE_SEC = 30.0

    def __init__ (
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

    def cleanup_old_records (self, max_age_sec: int = 5 * 3600) -> int:
        """
        Deletes sessions older than max_age_sec (default 5 hours) and their related data.

        This is a maintenance operation that should be invoked independently
        (e.g. via a cron job, Cloud Scheduler, or background worker).

        Uses batch delete operations to handle large volumes efficiently.
        Returns the number of cleaned-up sessions.
        """
        cutoff = time.time() - max_age_sec

        # 1. Server-side filtered query: fetch and delete sessions matching the age criterion
        old_sessions = self.db.delete_by_filter("sessions", {"created_at__lt": cutoff})
        if not old_sessions:
            return 0

        session_ids = [s["id"] for s in old_sessions]
        total_cleaned = len(session_ids)

        # 2. Batch-delete related data in chunks to avoid database engine parameter limits
        BATCH_SIZE = 500
        for i in range(0, total_cleaned, BATCH_SIZE):
            batch_ids = session_ids[i : i + BATCH_SIZE]

            # Cancel any pending updates for these sessions to prevent orphan loops
            for s_id in batch_ids:
                self.scheduler.cancel_update(s_id)

            # Clear actions, rate limits, and game states tied to these sessions
            self.db.delete_by_filter("actions", {"session_id__in": batch_ids})
            self.db.delete_by_filter("rate_limits", {"session_id__in": batch_ids})
            self.db.delete_by_filter("states", {"id__in": batch_ids})
            
            # Also clear any lingering loop locks
            self.db.delete_by_filter("locks", {"session_id__in": batch_ids})

        return total_cleaned

    def create_session (
        self, game_id: str, auth_token: str, role: Role = Role.PLAYER, custom_data: dict[str, Any] | None = None
    ) -> SessionResponse:
        """
        Creates a new session, generates tokens, and schedules the first update.
        """
        if game_id not in self.games:
            raise ValueError(f"Unknown game: {game_id}")

        # Verify requester using external auth token
        player = self.security.verify_identity(auth_token, role)
        if not player:
            raise PermissionError("Player not registered or invalid auth token, please register first")

        # Fetch Game Configurations
        config_data = self.db.read("game_configs", game_id) or {}
        config_data.pop("id", None)
        config_data.pop("game_id", None)
        config = GameConfig(game_id=game_id, **config_data)

        # Handle Matchmaking Wait-and-Join
        if custom_data and custom_data.get("matchmaking"):
            MAX_CAS_RETRIES = 3
            query_filters = {"game_id": game_id, "status": SessionStatus.MATCHMAKING}

            # If a specific lobby is requested, filter by it.
            # Otherwise, only match with sessions that have NO lobby_id (general matchmaking).
            join_lobby_id = custom_data.get("join_lobby")
            query_filters["lobby_id"] = join_lobby_id

            for _attempt in range(MAX_CAS_RETRIES + 1):
                waiting_sessions = self.db.query("sessions", query_filters)

                for session_data in waiting_sessions:
                    s_id = session_data.get("id")
                    if not s_id:
                        continue
                    session_data.pop("id", None)
                    session = Session(**session_data)

                    if player.player_id in session.players:
                        continue  # Player is already in this session

                    # 1. ATOMIC CLAIM: Try to reserve this session by switching status to CLAIMED.
                    # This prevents other concurrent callers from even trying to join this specific record.
                    original_status = session.status
                    current_version = session.version
                    
                    claim_session = copy.deepcopy(session)
                    claim_session.status = SessionStatus.CLAIMED
                    claim_session.version = current_version + 1
                    
                    claim_data = asdict(claim_session)
                    claim_data["id"] = s_id
                    
                    if not self.db.update("sessions", s_id, claim_data, expected_version=current_version):
                        continue # Failed to claim, somebody else got it or version moved. Try next candidate.

                    # 2. JOIN LOGIC: We now "own" the session's join process for this tick.
                    session = claim_session # Continue with the claimed session
                    current_version = session.version

                    try:
                        player.token = self.security.generate_session_token(player.player_id, s_id, role)
                        session.players[player.player_id] = player

                        state_data = self.db.read("states", s_id)
                        if not state_data:
                            # If state is missing, rollback claim and skip
                            session.status = original_status
                            session.version += 1
                            self.db.update("sessions", s_id, asdict(session))
                            continue

                        state_data.pop("id", None)
                        state = GameState(**state_data)

                        self.db.start_transaction()
                        try:
                            # Assign sticky slot if not already assigned
                            if not self._assign_player_slot(state, player, config, self.games[game_id]):
                                # This should not happen if max_players is respected, but safety first.
                                self.db.rollback()
                                continue

                            # Initialize player-specific state (private and potentially public adjustments)
                            state = self.games[game_id].setup_player_state(state, player)

                            # Determine next status: ACTIVE if full, otherwise back to MATCHMAKING
                            if len(session.players) >= config.max_players:
                                session.status = SessionStatus.ACTIVE
                            else:
                                session.status = SessionStatus.MATCHMAKING

                            session.version = current_version + 1
                            updated_session_data = asdict(session)
                            updated_session_data["id"] = s_id

                            # Final update for session (releases claim via status change)
                            if not self.db.update("sessions", s_id, updated_session_data,
                                                expected_version=current_version):
                                # This shouldn't happen if CLAIMED status is respected, but safety first.
                                self.db.rollback()
                                continue

                            # Update state
                            updated_state_data = asdict(state)
                            updated_state_data["id"] = s_id
                            self.db.update("states", s_id, updated_state_data)
                            
                            self.db.commit()
                        except Exception:
                            self.db.rollback()
                            raise

                        client_state = state.to_player_state(player.player_id)
                        return SessionResponse(
                            session_id=s_id,
                            token=player.token,
                            state=client_state,
                            lobby_id=session.lobby_id
                        )
                    
                    except Exception:
                        # If anything fails during join while claimed, we MUST release the claim
                        # by putting it back to MATCHMAKING (best effort).
                        session.status = SessionStatus.MATCHMAKING
                        session.version += 1
                        self.db.update("sessions", s_id, asdict(session))
                        raise

        # Create Session Object
        session_id = str(uuid.uuid4())
        current_time = time.time()

        # Generate a stateless session token for the player
        player.token = self.security.generate_session_token(player.player_id, session_id, role)

        initial_status = SessionStatus.MATCHMAKING if (custom_data and custom_data.get("matchmaking")) else SessionStatus.ACTIVE

        lobby_id = None
        if custom_data and custom_data.get("create_lobby"):
            # Generate a 6-letter uppercase ID (QOEMDU) using deterministic seeding.
            # Use hashlib.sha256 for a stable hash across serverless instances/retries.
            # Incorporate player_id and game_id to maintain consistency.
            seed_material = f"{player.player_id}:{game_id}".encode()
            seed = int(hashlib.sha256(seed_material).hexdigest(), 16) % (2**32)
            
            lobby_rng = random.Random(seed)
            letters = string.ascii_uppercase
            lobby_id = ''.join(lobby_rng.choice(letters) for i in range(6))
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

        # Initialize random seed from system entropy (only non-deterministic point)
        game_state.random_seed = random.getrandbits(64)

        # Assign first sticky slot
        self._assign_player_slot(game_state, player, config, self.games[game_id])

        # Save to database
        session_data = asdict(session)
        session_data["id"] = session_id
        state_data = asdict(game_state)
        state_data["id"] = session_id

        self.db.start_transaction()
        try:
            self.db.create("sessions", session_data)
            self.db.create("states", state_data)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        # Schedule the first update loop using the interface
        self.scheduler.schedule_next_update(session_id, config.update_interval_ms)

        # Prepare and return initial state for the requester with their specific private state
        client_state = game_state.to_player_state(player.player_id)

        return SessionResponse(
            session_id=session_id,
            token=player.token,
            state=client_state,
            lobby_id=lobby_id
        )

    def leave_session (self, session_id: str, player_id: str, token: str) -> bool:
        """
        Removes a player from a session and vacates their slot.
        """
        if not self.security.validate_request_token(session_id, player_id, token):
            return False

        # 1. Load Session
        session_data = self.db.read("sessions", session_id)
        if not session_data or player_id not in session_data.get("players", {}):
            return False

        session_data.pop("id", None)
        session = Session(**session_data)

        # 2. Load State
        state_data = self.db.read("states", session_id)
        if not state_data:
            return False

        state_data.pop("id", None)
        state = GameState(**state_data)

        # 3. Load Game Config for max_players
        config_data = self.db.read("game_configs", session.game_id) or {}
        config_data.pop("id", None)
        config_data.pop("game_id", None)
        config = GameConfig(game_id=session.game_id, **config_data)

        self.db.start_transaction()
        try:
            # 1. Update Session
            session.players.pop(player_id, None)
            
            # If the session was ACTIVE and now has room, put it back to MATCHMAKING
            # to allow others to join via matchmaking.
            if session.status == SessionStatus.ACTIVE and len(session.players) < config.max_players:
                session.status = SessionStatus.MATCHMAKING

            updated_session_data = asdict(session)
            updated_session_data["id"] = session_id
            self.db.update("sessions", session_id, updated_session_data)

            # 2. Update Game State
            # Vacate the slot
            slot_to_vacate = None
            for slot_id, p_id in state.slots.items():
                if p_id == player_id:
                    slot_to_vacate = slot_id
                    break
            
            if slot_to_vacate:
                state.slots.pop(slot_to_vacate)
            
            updated_state_data = asdict(state)
            updated_state_data["id"] = session_id
            self.db.update("states", session_id, updated_state_data)
            
            # 3. Cleanup nonces and acks
            self.db.delete_by_filter("nonces", {"session_id": session_id, "player_id": player_id})
            state.phase_ack.pop(player_id, None)

            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def _assign_player_slot (self, state: GameState, player: Player, config: GameConfig, rules: GameRules) -> bool:
        """
        Assigns a player to the first available slot based on game-defined priorities.
        """
        if player.player_id in state.slots.values():
            return True # Already assigned

        priorities = rules.get_slot_priority()
        
        for slot_id in priorities:
            if slot_id not in state.slots:
                state.slots[slot_id] = player.player_id
                return True

        return False # No available slots (should be blocked by max_players check)

    # Framework-reserved action types handled natively by the engine.
    FRAMEWORK_ACTIONS = frozenset({"ack"})

    def register_action (
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

        # Load game config for rate limit threshold
        config_data = self.db.read("game_configs", session.game_id) or {}
        config_data.pop("id", None)
        config_data.pop("game_id", None)
        config = GameConfig(game_id=session.game_id, **config_data)

        # --- Native framework action: ack (exempt from rate limiting) ---
        if action_type == "ack":
            return self._handle_ack(session_id, session, player_id, current_time)

        # Anti-spam check (Atomic: checks AND records in one operation)
        if not self.validator.check_and_record_rate_limit(session_id, player_id, current_time, config.min_action_gap_ms):
            return False

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

    def _handle_ack (
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

    def _try_acquire_loop_lock (
        self, session_id: str, holder_id: str, lease_sec: float = DEFAULT_LOOP_LEASE_SEC
    ) -> bool:
        """
        Attempts to acquire a distributed lease for a session's update loop.
        Uses CAS to prevent concurrent loop execution in serverless environments.
        Returns True if the lock was acquired, False otherwise.
        """
        lock_id = f"loop_{session_id}"
        now = time.time()

        existing = self.db.read("locks", lock_id)

        if existing is None:
            # No lock exists — attempt atomic creation. fail_if_exists=True ensures
            # that if two callers race here, only one succeeds; the other gets None.
            created = self.db.create("locks", {
                "id": lock_id,
                "session_id": session_id,
                "holder_id": holder_id,
                "expires_at": now + lease_sec,
                "version": 0,
            }, fail_if_exists=True)
            return created is not None

        # Lock exists and is still valid — another instance holds it.
        if existing.get("expires_at", 0) > now:
            return False

        # Lock is expired — attempt CAS takeover.
        current_version = existing.get("version", 0)
        new_lock = {
            "id": lock_id,
            "session_id": session_id,
            "holder_id": holder_id,
            "expires_at": now + lease_sec,
            "version": current_version + 1,
        }
        return self.db.update("locks", lock_id, new_lock, expected_version=current_version)

    def _release_loop_lock (self, session_id: str, holder_id: str) -> None:
        """
        Releases a previously acquired loop lock, but only if we still own it.
        """
        lock_id = f"loop_{session_id}"
        existing = self.db.read("locks", lock_id)
        if existing and existing.get("holder_id") == holder_id:
            self.db.delete("locks", lock_id)

    def process_update_loop (self, session_id: str) -> None:
        """
        The polling loop executed periodically. Processes pending actions and game state.
        This must be independent of other runs (Serverless requirement).

        Acquires a distributed lease before processing to ensure exactly one
        instance runs per session at a time. If the lock cannot be acquired,
        this invocation is silently skipped.
        """
        holder_id = str(uuid.uuid4())

        if not self._try_acquire_loop_lock(session_id, holder_id):
            return  # Another instance is already processing this session

        try:
            self._execute_update_loop(session_id)
        finally:
            self._release_loop_lock(session_id, holder_id)

    def _execute_update_loop (self, session_id: str) -> None:
        """Core update loop logic, called under distributed lock protection."""
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
        self.db.start_transaction()
        try:
            # Create deterministic RNG from saved seed
            rng = random.Random(state.random_seed)

            # Snapshot state for granular version bumping
            original_phase = state.public_state.get("phase")
            original_public = copy.deepcopy(state.public_state)
            original_private = copy.deepcopy(state.private_state)

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
                # Calculate real elapsed time based on database-stored timestamps
                if state.last_update_timestamp > 0:
                    raw_delta_ms = int((current_time - state.last_update_timestamp) * 1000)
                else:
                    # First tick after creation: no meaningful game time has elapsed
                    raw_delta_ms = 0

                # Clamp to prevent spikes from serverless cold starts or scheduling delays.
                # Uses 3x the configured interval as ceiling (minimum cap of 2000ms).
                max_delta = max(config.update_interval_ms * 3, 2000) if config.update_interval_ms > 0 else 2000
                delta_ms = max(0, min(raw_delta_ms, max_delta))

                state = rules.apply_update_tick(state, delta_ms, rng)

            # Always advance the timestamp — even during skipped (gated) ticks —
            # so that delta_ms doesn't spike when the gate clears.
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
                        state = rules.apply_action(action, state, rng)
                        # Update local state nonce to prevent replays
                        state.last_nonces[action.player_id] = action.nonce

                # Mark action as processed
                raw_act["processed"] = True
                self.db.update("actions", raw_act["id"], raw_act)

            # Granular versioning: bump on ANY state mutation so clients detect every change.
            if state.public_state != original_public or state.private_state != original_private:
                state.state_version += 1

            # Reset acks only on phase transitions (gated phases still need this).
            new_phase = state.public_state.get("phase")
            if new_phase != original_phase:
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
                self.db.commit()
                return  # Exit loop

            # 6. Save State and Reschedule
            # Always save to persist last_update_timestamp (prevents delta spikes
            # after gated phases) and the advanced random seed.
            state.random_seed = rng.randint(0, 2**63 - 1)
            state_data = asdict(state)
            state_data["id"] = session_id
            self.db.update("states", session_id, state_data)
            
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        # Enforce serverless minimum interval requirement (>=500ms)
        delay_ms = max(config.update_interval_ms, self.MINIMUM_UPDATE_INTERVAL_MS)
        self.scheduler.schedule_next_update(session_id, delay_ms)

    # Framework-reserved action types handled natively by the engine.
