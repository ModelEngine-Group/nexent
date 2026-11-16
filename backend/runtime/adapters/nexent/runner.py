# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Stable in-process invocation boundary for the current Nexent engine.

These are aliases to the existing implementation, so direct-stream cancellation,
pre-admitted execution and managed worker ownership remain unchanged.
"""

from nexent.core.agents.run_agent import DeferredAgentRun, agent_run

__all__ = ["DeferredAgentRun", "agent_run"]
