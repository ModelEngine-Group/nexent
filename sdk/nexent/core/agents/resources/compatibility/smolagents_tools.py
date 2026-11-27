# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit compatibility with existing tool and sandbox execution types."""

from smolagents.tools import Tool

from nexent.core.agents.resources.tool_schemas import parse_mcp_tool_inputs


def deferred_executor_type():
    from nexent.core.agents.cores.smolagents.tool_fastpath import DeferredToolExecutor
    return DeferredToolExecutor


def from_langchain(tool):
    return Tool.from_langchain(tool)


def mcp_adapter_factory():
    from mcpadapt.smolagents_adapter import SmolAgentsAdapter
    return SmolAgentsAdapter(structured_output=False)


def build_lazy_smolagents_tool(tool_config, call_fn) -> Tool:
    """Build a smolagents tool from the DB-cached schema without connecting.

    The live server is contacted lazily through ``call_fn`` at invocation
    time; the prompt-facing schema comes from the cached ToolConfig so agent
    construction never blocks on MCP availability.
    """
    from mcp.types import Tool as MCPTool

    adapter = mcp_adapter_factory()
    properties = parse_mcp_tool_inputs(tool_config)
    synthetic_tool = MCPTool(
        name=getattr(tool_config, "class_name", None) or getattr(tool_config, "name", None) or "unknown",
        description=getattr(tool_config, "description", None) or "",
        inputSchema={"type": "object", "properties": properties},
    )
    return adapter.adapt(call_fn, synthetic_tool)
