"""Shared client base for terminal game runners.

This module owns the reusable HTTP/session lifecycle so concrete game clients
can focus on phase-specific input, rendering, and action payloads.
"""

from __future__ import annotations

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
import jwt
from pyslap.config import settings

InputFunc = Callable[[str, str, int], Awaitable[str]]


@dataclass
class ClientRuntime:
    client: httpx.AsyncClient
    base_url: str
    session_id: str
    player_id: str
    token: str
    game_id: str
    nonce: int = 0
    last_state_version: int = -1
    final_state: dict[str, Any] | None = None


class GameClientBase(ABC):
    """Reusable runtime for a game client that talks to the local HTTP backend."""

    http_timeout = 30.0
    poll_delay = 0.25
    unchanged_state_delay = 0.5
    token_key_env_var = "PYSLAP_EXTERNAL_SECRET"
    token_key: str | None = None
    _default_external_secret = "pyslap_default_external_secret_32_bytes_min"
    _warned_default_secret = False
    token_lifetime_sec = 86400

    def build_custom_data(self, config: dict[str, Any]) -> dict[str, Any]:
        custom_data: dict[str, Any] = {"use_bot": config.get("use_bot", False)}
        if config.get("matchmaking"):
            custom_data["matchmaking"] = True
        if config.get("create_lobby"):
            custom_data["create_lobby"] = True
        if config.get("join_lobby"):
            custom_data["join_lobby"] = config["join_lobby"]
        return custom_data

    def build_auth_token(self, player_id: str, player_name: str) -> str:
        token_key = self.resolve_token_key()
        payload = {
            "player_id": player_id,
            "name": player_name,
            "exp": time.time() + self.token_lifetime_sec,
        }
        return jwt.encode(payload, token_key, algorithm="HS256")

    def resolve_token_key(self) -> str:
        token_key = os.getenv(self.token_key_env_var) or self.token_key or settings.external_secret
        if token_key:
            if token_key == self._default_external_secret and not self._warned_default_secret:
                print(
                    "[Warning] Using default external secret; set PYSLAP_EXTERNAL_SECRET for safer local/testing setup."
                )
                self._warned_default_secret = True
            return token_key
        raise RuntimeError(
            f"Missing auth signing key. Set {self.token_key_env_var} or override token_key on the client class."
        )

    async def start_session(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        game_id: str,
        auth_token: str,
        custom_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"game_id": game_id, "auth_token": auth_token}
        if custom_data:
            payload["custom_data"] = custom_data

        try:
            resp = await client.post(f"{base_url}/session", json=payload)
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            print(f"Unable to connect to server at {base_url}: {exc}")
            print("Tip: Make sure the API server is running and reachable.")
            return None
        except httpx.RequestError as exc:
            print(f"Network error while starting session: {exc}")
            return None

        if resp.status_code != 200:
            try:
                err_msg = resp.json().get("detail", f"Error: {resp.status_code} - {resp.text}")
            except Exception:
                err_msg = f"Error: {resp.status_code} - {resp.text}"
            print(err_msg)
            return None

        return resp.json()

    async def get_state(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        session_id: str,
        player_id: str,
        token: str,
    ) -> dict[str, Any] | None:
        try:
            resp = await client.get(
                f"{base_url}/state",
                params={"session_id": session_id, "player_id": player_id, "token": token},
            )
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            print(f"\n[Warning] Network error getting state: {exc}")
            return None
        except httpx.RequestError as exc:
            print(f"\n[Warning] Request error getting state: {exc}")
            return None

        if resp.status_code != 200:
            try:
                err_msg = resp.json().get("detail", f"Error: {resp.status_code} - {resp.text}")
            except Exception:
                err_msg = f"Error: {resp.status_code} - {resp.text}"
            print(f"\n[Warning] Failed to get state: {err_msg}")
            return None

        return resp.json()

    async def send_action(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        session_id: str,
        player_id: str,
        token: str,
        action_type: str,
        payload: dict[str, Any],
        nonce: int,
    ) -> bool:
        try:
            resp = await client.post(
                f"{base_url}/action",
                json={
                    "session_id": session_id,
                    "player_id": player_id,
                    "token": token,
                    "action_type": action_type,
                    "payload": payload,
                    "nonce": nonce,
                },
            )
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            print(f"\n[Warning] Network error sending action: {exc}")
            return False
        except httpx.RequestError as exc:
            print(f"\n[Warning] Request error sending action: {exc}")
            return False

        if resp.status_code != 200:
            try:
                err_msg = resp.json().get("detail", f"Error: {resp.status_code} - {resp.text}")
            except Exception:
                err_msg = f"Error: {resp.status_code} - {resp.text}"
            print(f"\n[Warning] Failed to send action: {err_msg}")
            return False

        return True

    async def read_input(self, prompt: str) -> str:
        loop = asyncio.get_running_loop()
        print(prompt, end="", flush=True)
        result = await loop.run_in_executor(None, input)
        return result.strip()

    async def read_input_with_timeout(self, prompt: str, timeout: float) -> str:
        loop = asyncio.get_running_loop()
        print(prompt, end="", flush=True)
        try:
            future = loop.run_in_executor(None, input)
            result = await asyncio.wait_for(future, timeout=timeout)
            stripped = result.strip()
            if stripped == "":
                return "<timeout>"
            return stripped
        except asyncio.TimeoutError:
            return "<timeout>"

    async def run_client(
        self,
        config: dict[str, Any],
        input_func: InputFunc | None = None,
    ) -> dict[str, Any] | None:
        base_url = config.get("base_url", "http://localhost:8000")
        player_id = config.get("player_id", "test_player")
        player_name = config.get("player_name", player_id.upper())
        game_id = config.get("game_id", self.default_game_id(config))

        custom_data = self.build_custom_data(config)
        try:
            auth_token = self.build_auth_token(player_id, player_name)
        except RuntimeError as exc:
            print(exc)
            return None

        async with httpx.AsyncClient(timeout=self.http_timeout) as client:
            response = await self.start_session(client, base_url, game_id, auth_token, custom_data)
            if response is None:
                return None

            runtime = ClientRuntime(
                client=client,
                base_url=base_url,
                session_id=response["session_id"],
                player_id=player_id,
                token=response["token"],
                game_id=game_id,
            )

            await self.on_session_started(runtime, response, config, input_func)

            while True:
                state = await self.get_state(client, runtime.base_url, runtime.session_id, runtime.player_id, runtime.token)
                if state is None:
                    await asyncio.sleep(self.poll_delay)
                    continue

                state_version = state.get("state_version", 0)
                if state_version == runtime.last_state_version:
                    await asyncio.sleep(self.unchanged_state_delay)
                    continue

                runtime.last_state_version = state_version
                finished = await self.handle_state(runtime, state, input_func)
                if finished:
                    return runtime.final_state

                await asyncio.sleep(self.poll_delay)

    def default_game_id(self, config: dict[str, Any]) -> str:
        return config.get("game_id", "")

    async def on_session_started(
        self,
        runtime: ClientRuntime,
        session_response: dict[str, Any],
        config: dict[str, Any],
        input_func: InputFunc | None,
    ) -> None:
        return None

    @abstractmethod
    async def handle_state(
        self,
        runtime: ClientRuntime,
        state: dict[str, Any],
        input_func: InputFunc | None,
    ) -> bool:
        """Handle a freshly observed game state.

        Return True when the client should stop and return the final state.
        """
