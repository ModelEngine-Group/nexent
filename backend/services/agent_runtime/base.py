"""Runtime provider protocol."""

from collections.abc import AsyncIterator
from typing import Protocol

from .execution import AgentRuntimeExecution


class AgentRuntime(Protocol):
    """Common lifecycle implemented by both in-process frameworks."""

    async def run(self, execution: AgentRuntimeExecution) -> AsyncIterator[str]:
        """Yield legacy Nexent event chunks for one execution."""

    def request_stop(self, run_id: str) -> bool:
        """Signal one active run without blocking the HTTP stop path."""

    async def shutdown(self) -> None:
        """Drain resources owned by an initialized provider."""
