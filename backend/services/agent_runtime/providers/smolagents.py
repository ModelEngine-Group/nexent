"""Existing Smolagents execution exposed through the common provider interface."""

from collections.abc import AsyncIterator
from threading import RLock

from nexent.core.agents.run_agent import agent_run

from ..execution import AgentRuntimeExecution


class SmolagentsRuntime:
    """Run the existing AgentRunInfo path without importing OpenJiuwen."""

    def __init__(self) -> None:
        self._stop_events: dict[str, object] = {}
        self._lock = RLock()

    async def run(self, execution: AgentRuntimeExecution) -> AsyncIterator[str]:
        with self._lock:
            self._stop_events[execution.run_id] = execution.agent_run_info.stop_event
        try:
            async for chunk in agent_run(execution.agent_run_info):
                yield chunk
        finally:
            with self._lock:
                self._stop_events.pop(execution.run_id, None)

    def request_stop(self, run_id: str) -> bool:
        with self._lock:
            stop_event = self._stop_events.get(run_id)
        if stop_event is None:
            return False
        stop_event.set()
        return True

    async def shutdown(self) -> None:
        with self._lock:
            stop_events = list(self._stop_events.values())
        for stop_event in stop_events:
            stop_event.set()


def create_runtime() -> SmolagentsRuntime:
    """Create the local Smolagents provider."""
    return SmolagentsRuntime()


__all__ = ["SmolagentsRuntime", "create_runtime"]
