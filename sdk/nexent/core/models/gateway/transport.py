"""Transport-layer abstraction, orthogonal to modality logic.

Inspired by Pipecat's ``WebsocketService`` mixin design: transport concerns
(HTTP base_url/api_key vs WebSocket ws_url/auth_headers) live in mixins that
are multiply-inherited alongside a modality ABC, decoupling
``BaseSTTModel``/``BaseTTSModel`` from their hardcoded WebSocket assumption.
An HTTP-only vendor (e.g. ModelEngine STT/TTS) can therefore take
:class:`HttpTransportMixin` instead of ``WebSocketTransportMixin``.
"""

from abc import ABC, abstractmethod
from typing import Optional


class Transport(ABC):
    """Transport-layer contract, orthogonal to modality logic."""

    transport_type: str  # "http" | "websocket"

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying transport session (lazy for HTTP)."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the underlying transport session."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the transport endpoint is reachable."""


class HttpTransportMixin:
    """HTTP REST transport capability.

    Adapter classes multiply-inherit this alongside their modality ABC to gain
    HTTP transport attributes without polluting the modality interface.
    """

    transport_type = "http"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        ssl_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._ssl_verify = ssl_verify
        self._timeout = timeout

    async def connect(self) -> None:  # HTTP clients are created lazily per-call.
        return None

    async def close(self) -> None:
        return None

    async def health_check(self) -> bool:
        # Delegated to the adapter's wrapped model; the mixin only carries state.
        return True


class WebSocketTransportMixin:
    """WebSocket transport capability.

    WS-specific parameters (ws_url, auth_headers) are managed here rather than
    on the modality ABC, so ``BaseSTTModel``/``BaseTTSModel`` no longer need to
    hardcode WebSocket assumptions. The session is created lazily.
    """

    transport_type = "websocket"

    def __init__(
        self,
        *,
        ws_url: Optional[str] = None,
        auth_headers: Optional[dict] = None,
    ) -> None:
        self._ws_url = ws_url
        self._auth_headers = auth_headers or {}
        self._ws_session = None  # websockets.ClientConnection, created lazily

    async def connect(self) -> None:
        # The wrapped model owns its WS lifecycle; the mixin only carries state.
        return None

    async def close(self) -> None:
        if self._ws_session is not None:
            try:
                await self._ws_session.close()
            finally:
                self._ws_session = None

    async def health_check(self) -> bool:
        return self._ws_url is not None
