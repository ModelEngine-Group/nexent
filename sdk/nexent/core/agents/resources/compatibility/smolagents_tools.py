# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit compatibility with existing tool and sandbox execution types."""

from smolagents.tools import Tool


def deferred_executor_type():
    from nexent.core.agents.cores.smolagents.tool_fastpath import DeferredToolExecutor
    return DeferredToolExecutor


def from_langchain(tool):
    return Tool.from_langchain(tool)


def mcp_adapter_factory():
    from mcpadapt.smolagents_adapter import SmolAgentsAdapter
    return SmolAgentsAdapter(structured_output=False)
