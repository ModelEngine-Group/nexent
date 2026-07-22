"""Framework-neutral execution context passed to in-process runtimes."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentRuntimeExecution:
    """All request identity and assembled resources required by a runtime."""

    run_id: str
    agent_run_info: Any
    conversation_id: int
    user_id: str
    tenant_id: str
    version_no: int


__all__ = ["AgentRuntimeExecution"]
