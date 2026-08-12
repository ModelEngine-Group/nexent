"""Transport-layer abstraction, orthogonal to modality logic.

Inspired by Pipecat's ``WebsocketService`` mixin design: transport concerns
(HTTP base_url/api_key vs WebSocket ws_url/auth_headers) live in mixins that
are multiply-inherited alongside a modality ABC, decoupling the STT/TTS
adapters from a hardcoded WebSocket assumption. An HTTP-only vendor (e.g.
ModelEngine STT/TTS) can therefore take :class:`HttpTransportMixin` instead of
``WebSocketTransportMixin``.
"""

from abc import ABC, abstractmethod
from typing import Optional


class Transport(ABC):
    """Transport-layer contract, orthogonal to modality logic.

    Attributes:
        transport_type: ``"http"`` or ``"websocket"``.
    """

    transport_type: str  # "http" | "websocket"

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying transport session (lazy for HTTP)."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the underlying transport session."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the transport endpoint is reachable.

        Returns:
            True if the endpoint is reachable, False otherwise.
        """


class HttpTransportMixin:
    """HTTP REST transport capability.

    Adapter classes multiply-inherit this alongside their modality ABC to gain
    HTTP transport attributes without polluting the modality interface.

    Attributes:
        transport_type: Always ``"http"``.
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
        """Stores HTTP transport state for later per-call use.

        Args:
            base_url: The HTTP endpoint URL.
            api_key: The bearer token used for authorization.
            ssl_verify: Whether to verify TLS certificates.
            timeout: Default request timeout in seconds.
        """
        self._base_url = base_url
        self._api_key = api_key
        self._ssl_verify = ssl_verify
        self._timeout = timeout

    async def connect(self) -> None:
        """No-op: HTTP clients are created lazily per-call."""
        return None

    async def close(self) -> None:
        """No-op: there is no persistent HTTP session to close."""
        return None

    async def health_check(self) -> bool:
        """Returns True; connectivity is the adapter's responsibility.

        Returns:
            Always True (the mixin only carries state).
        """
        # Delegated to the adapter's wrapped model; the mixin only carries state.
        return True


class WebSocketTransportMixin:
    """WebSocket transport capability.

    WS-specific parameters (ws_url, auth_headers) are managed here rather than
    on the modality ABC, so STT/TTS adapters no longer need to hardcode
    WebSocket assumptions. The session is created lazily.

    Attributes:
        transport_type: Always ``"websocket"``.
    """

    transport_type = "websocket"

    def __init__(
        self,
        *,
        ws_url: Optional[str] = None,
        auth_headers: Optional[dict] = None,
    ) -> None:
        """Stores WebSocket transport state for later lazy connection.

        Args:
            ws_url: The WebSocket endpoint URL.
            auth_headers: Optional authentication headers sent on connect.
        """
        self._ws_url = ws_url
        self._auth_headers = auth_headers or {}
        self._ws_connection = None  # websockets.ClientConnection, created lazily

    async def connect(self) -> None:
        """No-op: the wrapped model owns its WS lifecycle."""
        return None

    async def close(self) -> None:
        """Closes the lazily-created WebSocket connection, if any.

        Idempotent: clears ``_ws_connection`` even on close failure.
        """
        if self._ws_connection is not None:
            try:
                await self._ws_connection.close()
            finally:
                self._ws_connection = None

    async def health_check(self) -> bool:
        """Returns whether a WebSocket URL is configured.

        Returns:
            True if ``ws_url`` is set, False otherwise.
        """
        return self._ws_url is not None
