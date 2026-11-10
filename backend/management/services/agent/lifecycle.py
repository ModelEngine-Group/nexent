# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compatibility imports for the legacy Agent execution callers."""

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
