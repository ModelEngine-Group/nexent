"""Small Nacos 3.x A2A registry client with optional authentication."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx

from .cards import card_dict
from .config import Settings


@dataclass
class RegistryState:
    registered: bool = False
    last_error: str | None = None


class NacosRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state = RegistryState()
        self._token: str | None = None

    async def _login(self, client: httpx.AsyncClient) -> str | None:
        response = await client.post(
            self.settings.nacos_login_path,
            data={"username": self.settings.nacos_username, "password": self.settings.nacos_password},
        )
        if response.status_code == 403:
            bootstrap = await client.post(
                self.settings.nacos_admin_init_path,
                data={
                    "username": self.settings.nacos_username,
                    "password": self.settings.nacos_password,
                },
            )
            bootstrap.raise_for_status()
            response = await client.post(
                self.settings.nacos_login_path,
                data={
                    "username": self.settings.nacos_username,
                    "password": self.settings.nacos_password,
                },
            )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("accessToken") or (payload.get("data") or {}).get("accessToken")
        if not token:
            raise RuntimeError("Nacos login response did not contain an access token")
        return str(token)

    async def register_once(self) -> None:
        async with httpx.AsyncClient(base_url=self.settings.nacos_server_url, timeout=10) as client:
            self._token = await self._login(client)
            headers = {"accessToken": self._token} if self._token else {}
            card = card_dict(
                self.settings.advertised_base_url,
                "basic",
                name=self.settings.nacos_agent_name,
            )
            response = await client.post(
                self.settings.nacos_register_path,
                headers=headers,
                data={
                    "namespaceId": self.settings.nacos_namespace,
                    "agentName": self.settings.nacos_agent_name,
                    "registrationType": self.settings.nacos_registration_type,
                    "agentCard": json.dumps(card, ensure_ascii=False),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (None, 0, 200) and payload.get("data") not in (
                "ok",
                "true",
                "success",
            ):
                raise RuntimeError(f"Nacos rejected A2A registration: {payload}")
            self.state = RegistryState(registered=True)

    async def register_with_retry(self) -> None:
        for attempt in range(1, self.settings.nacos_retry_count + 1):
            try:
                await self.register_once()
                return
            except Exception as exc:  # Registration evidence keeps the final external failure.
                self.state = RegistryState(registered=False, last_error=f"{type(exc).__name__}: {exc}")
                if attempt < self.settings.nacos_retry_count:
                    await asyncio.sleep(self.settings.nacos_retry_seconds)

    async def deregister(self) -> None:
        if not self.state.registered:
            return
        try:
            async with httpx.AsyncClient(base_url=self.settings.nacos_server_url, timeout=10) as client:
                headers = {"accessToken": self._token} if self._token else {}
                response = await client.delete(
                    self.settings.nacos_register_path,
                    headers=headers,
                    params={
                        "namespaceId": self.settings.nacos_namespace,
                        "agentName": self.settings.nacos_agent_name,
                    },
                )
                response.raise_for_status()
            self.state = RegistryState(registered=False)
        except Exception as exc:
            self.state.last_error = f"{type(exc).__name__}: {exc}"
