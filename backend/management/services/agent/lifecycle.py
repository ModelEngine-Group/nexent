# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compatibility imports for the legacy Agent execution callers."""

from nexent.core.concurrency import ThreadManager, get_default_thread_manager
from runtime.executions import (
    AgentRunAlreadyActiveError,
    AgentRunConcurrencyExceededError,
    AgentRunManager,
    agent_run_manager,
)

__all__ = [
    "AgentRunAlreadyActiveError",
    "AgentRunConcurrencyExceededError",
    "AgentRunManager",
    "agent_run_manager",
]


def require_legacy_thread_manager(thread_manager: ThreadManager | None) -> ThreadManager:
    """Resolve the explicitly bound pool or the process's installed SDK pool."""
    if thread_manager is None:
        thread_manager = get_default_thread_manager()
    if thread_manager is None:
        raise RuntimeError("Legacy Agent execution requires a thread manager")
    return thread_manager
