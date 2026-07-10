"""Runtime adapter protocol shared by backend runtime implementations."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from .models import RuntimeCapabilities


class AgentRuntime(Protocol):
    """Framework-neutral interface implemented by agent runtime adapters."""

    name: str
    capabilities: RuntimeCapabilities

    def run(self, plan: Any, event_sink: Any) -> AsyncIterator[Any]:
        """Execute a prepared run plan and stream runtime output."""
        ...

    async def stop(self, request_id: str) -> None:
        """Cancel a request-scoped active run."""
        ...
